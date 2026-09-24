"""Поведение кэша голосования (ТЗ п.20, 21, 114)."""
from unittest import mock

from django.core.cache import caches
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.core.cache_keys import student_vote_status
from apps.students.models import Student
from apps.students.services_auth import create_student_token
from apps.voting.models import Ballot, VoteRecord

from .base import ContractTestCase
from .factories import make_candidate, make_election, make_university

SERVICE = ("SAVEPOINT", "RELEASE", "ROLLBACK", "pg_advisory", "BEGIN", "COMMIT")


def real_sql(captured):
    return [q["sql"] for q in captured if not any(m in q["sql"] for m in SERVICE)]


class VoteStatusCacheTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        caches["default"].clear()
        self.uni = make_university()
        self.student = Student.objects.create(
            university=self.uni, student_id="S-1", full_name="Тест", course=1
        )
        self.election = make_election(self.uni)
        self.candidate = make_candidate(self.election)
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {create_student_token(self.student)}"}
        self.status_url = f"/api/v1/voting/status/{self.election.id}/"
        self.client.get(self.status_url, **self.headers)  # прогрев кэша личности

    def _cast(self):
        """Голосует, выполняя колбэки on_commit.

        Внутри TestCase всё завёрнуто в транзакцию, которая никогда не
        коммитится, поэтому transaction.on_commit сам по себе не сработает.
        captureOnCommitCallbacks(execute=True) воспроизводит поведение
        production, где коммит настоящий.
        """
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                "/api/v1/voting/cast/",
                {"election_id": str(self.election.id), "candidate_id": str(self.candidate.id)},
                format="json", **self.headers,
            )

    def test_status_after_vote_needs_no_sql(self):
        self._cast()
        with CaptureQueriesContext(connection) as ctx:
            res = self.client.get(self.status_url, **self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["has_voted"])
        self.assertEqual(
            real_sql(ctx.captured_queries), [],
            "статус после голоса должен читаться из кэша без обращений к базе",
        )

    def test_cached_and_database_answers_are_identical(self):
        """Ответ не должен зависеть от того, попали мы в кэш или нет.

        Ловит класс ошибок, где кэш хранит упрощённое значение (например,
        флаг вместо метки времени) и endpoint начинает отдавать разное.
        """
        self._cast()
        from_cache = self.client.get(self.status_url, **self.headers).data

        caches["default"].clear()
        self.client.get(self.status_url, **self.headers)  # прогрев личности
        caches["default"].delete(
            student_vote_status(self.student.id, self.election.id)
        )
        from_db = self.client.get(self.status_url, **self.headers).data

        self.assertEqual(
            dict(from_cache), dict(from_db),
            "ответ из кэша отличается от ответа из базы",
        )
        self.assertIsNotNone(from_cache["voted_at"])

    def test_negative_status_is_not_cached(self):
        """ТЗ п.21: устаревшее «не голосовал» показало бы кнопку повторно."""
        self.client.get(self.status_url, **self.headers)
        self.assertIsNone(
            caches["default"].get(student_vote_status(self.student.id, self.election.id)),
            "отрицательный статус не должен попадать в кэш",
        )

    def test_cache_is_set_only_after_commit(self):
        """При откате транзакции кэш не должен остаться заполненным."""
        key = student_vote_status(self.student.id, self.election.id)
        with self.captureOnCommitCallbacks(execute=True):
            with mock.patch.object(Ballot.objects, "create", side_effect=RuntimeError("сбой")):
                with self.assertRaises(RuntimeError):
                    from apps.voting.services import cast_secret_ballot
                    cast_secret_ballot(self.student, str(self.election.id), str(self.candidate.id))
        self.assertIsNone(caches["default"].get(key),
                          "кэш поставлен при откатившейся транзакции")

    def test_cache_self_heals_after_flush(self):
        self._cast()
        caches["default"].clear()
        res = self.client.get(self.status_url, **self.headers)
        self.assertTrue(res.data["has_voted"], "статус должен читаться из базы после очистки")
        self.assertIsNotNone(
            caches["default"].get(student_vote_status(self.student.id, self.election.id)),
            "кэш должен восстановиться после промаха",
        )

    def test_status_correct_when_cache_unavailable(self):
        import redis

        self._cast()
        with mock.patch.object(
            caches["default"], "get", side_effect=redis.ConnectionError("нет Redis")
        ):
            res = self.client.get(self.status_url, **self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["has_voted"])


class RedisFlushDoesNotAffectVotesTest(ContractTestCase):
    """ТЗ п.114 — обязательный тест.

    Если Redis полностью очищен, все подтверждённые голоса остаются
    корректными в PostgreSQL.
    """

    def setUp(self):
        super().setUp()
        caches["default"].clear()
        self.uni = make_university()
        self.election = make_election(self.uni)
        self.candidates = [make_candidate(self.election, full_name=f"К{i}", order=i)
                           for i in range(3)]
        self.students = [
            Student.objects.create(university=self.uni, student_id=f"S-{i}",
                                   full_name=f"Студент {i}", course=1)
            for i in range(10)
        ]

    def test_votes_survive_full_cache_flush(self):
        for index, student in enumerate(self.students):
            headers = {"HTTP_AUTHORIZATION": f"Bearer {create_student_token(student)}"}
            with self.captureOnCommitCallbacks(execute=True):
                res = self.client.post(
                    "/api/v1/voting/cast/",
                    {"election_id": str(self.election.id),
                     "candidate_id": str(self.candidates[index % 3].id)},
                    format="json", **headers,
                )
            self.assertEqual(res.status_code, 200)

        tally_before = {
            c.id: Ballot.objects.filter(election=self.election, candidate=c).count()
            for c in self.candidates
        }

        caches["default"].clear()

        self.assertEqual(VoteRecord.objects.filter(election=self.election).count(), 10)
        self.assertEqual(Ballot.objects.filter(election=self.election).count(), 10)
        tally_after = {
            c.id: Ballot.objects.filter(election=self.election, candidate=c).count()
            for c in self.candidates
        }
        self.assertEqual(tally_before, tally_after, "очистка Redis изменила результаты")

    def test_api_keeps_working_after_flush(self):
        student = self.students[0]
        headers = {"HTTP_AUTHORIZATION": f"Bearer {create_student_token(student)}"}
        self.client.post(
            "/api/v1/voting/cast/",
            {"election_id": str(self.election.id), "candidate_id": str(self.candidates[0].id)},
            format="json", **headers,
        )
        caches["default"].clear()

        status_res = self.client.get(f"/api/v1/voting/status/{self.election.id}/", **headers)
        self.assertEqual(status_res.status_code, 200)
        self.assertTrue(status_res.data["has_voted"])

        profile = self.client.get("/api/v1/auth/student/me/", **headers)
        self.assertEqual(profile.status_code, 200)

    def test_double_vote_still_blocked_after_flush(self):
        """Защита от дубля держится на констрейнте базы, а не на кэше."""
        student = self.students[0]
        headers = {"HTTP_AUTHORIZATION": f"Bearer {create_student_token(student)}"}
        payload = {"election_id": str(self.election.id),
                   "candidate_id": str(self.candidates[0].id)}
        self.client.post("/api/v1/voting/cast/", payload, format="json", **headers)

        caches["default"].clear()

        second = self.client.post("/api/v1/voting/cast/", payload, format="json", **headers)
        self.assertEqual(second.status_code, 400)
        self.assertErrorEnvelope(second, "already_voted")
        self.assertEqual(VoteRecord.objects.filter(election=self.election).count(), 1)
