"""Кэш не должен раскрывать скрытые результаты (ТЗ п.51, 22, 24)."""
from django.core.cache import caches

from apps.core.cache_keys import election_public, election_results, election_turnout
from apps.elections.models import Election
from apps.students.models import Student
from apps.students.services_auth import create_student_token

from .base import ContractTestCase
from .factories import make_admin, make_candidate, make_election, make_university


class HiddenResultsCacheTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        caches["default"].clear()
        self.uni = make_university()
        self.election = make_election(self.uni)
        self.candidate = make_candidate(self.election)
        self.student = Student.objects.create(
            university=self.uni, student_id="S-1", full_name="Тест", course=1
        )
        headers = {"HTTP_AUTHORIZATION": f"Bearer {create_student_token(self.student)}"}
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                "/api/v1/voting/cast/",
                {"election_id": str(self.election.id), "candidate_id": str(self.candidate.id)},
                format="json", **headers,
            )
        self.admin = make_admin(email="super@test.kg")
        self.as_admin(self.admin)

    def test_active_election_results_are_not_cached(self):
        """Кэш итогов идущих выборов пережил бы смену состояния."""
        self.client.get(f"/api/v1/admin/elections/{self.election.id}/turnout/")
        self.assertIsNone(
            caches["default"].get(election_results(self.election.id)),
            "итоги идущих выборов не должны попадать в кэш",
        )

    def test_hidden_results_stay_hidden_even_with_warm_cache(self):
        """Прогрев кэша не должен открыть результаты раньше времени."""
        self.election.results_visible_to_admin_before_finish = True
        self.election.save(update_fields=["results_visible_to_admin_before_finish"])
        warm = self.client.get(f"/api/v1/admin/elections/{self.election.id}/results/")
        self.assertEqual(warm.status_code, 200)

        self.election.results_visible_to_admin_before_finish = False
        self.election.save(update_fields=["results_visible_to_admin_before_finish"])

        res = self.client.get(f"/api/v1/admin/elections/{self.election.id}/results/")
        self.assertEqual(res.status_code, 403)
        self.assertErrorEnvelope(res, "results_hidden")

    def test_turnout_cache_does_not_contain_candidate_breakdown(self):
        """Ключи раздельные: кэш явки не должен нести результаты."""
        self.client.get(f"/api/v1/admin/elections/{self.election.id}/turnout/")
        cached = caches["default"].get(election_turnout(self.election.id))
        self.assertIsNotNone(cached)
        self.assertNotIn("candidates", cached)
        self.assertNotIn(str(self.candidate.id), str(cached))

    def test_finished_results_are_cached(self):
        self.client.post(f"/api/v1/admin/elections/{self.election.id}/finish/")
        self.client.get(f"/api/v1/admin/elections/{self.election.id}/results/")
        self.assertIsNotNone(
            caches["default"].get(election_results(self.election.id)),
            "итоги завершённых выборов должны кэшироваться (ТЗ п.28)",
        )


class CacheInvalidationTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        caches["default"].clear()
        self.uni = make_university()
        self.election = make_election(self.uni)
        self.candidate = make_candidate(self.election)
        self.admin = make_admin(email="super@test.kg")
        self.as_admin(self.admin)

    def _warm_turnout(self):
        self.client.get(f"/api/v1/admin/elections/{self.election.id}/turnout/")
        self.assertIsNotNone(caches["default"].get(election_turnout(self.election.id)))

    def test_finish_invalidates_election_cache(self):
        self._warm_turnout()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/api/v1/admin/elections/{self.election.id}/finish/")
        self.assertIsNone(
            caches["default"].get(election_turnout(self.election.id)),
            "смена состояния обязана сбросить кэш выборов",
        )

    def test_election_update_invalidates_cache(self):
        self._warm_turnout()
        self.client.patch(
            f"/api/v1/admin/elections/{self.election.id}/",
            {"title": "Переименованные"}, format="json",
        )
        self.assertIsNone(caches["default"].get(election_turnout(self.election.id)))

    def test_candidate_create_invalidates_election_cache(self):
        self._warm_turnout()
        self.client.post(
            f"/api/v1/admin/elections/{self.election.id}/candidates/",
            {"full_name": "Новый кандидат"}, format="json",
        )
        self.assertIsNone(caches["default"].get(election_turnout(self.election.id)))

    def test_candidate_delete_invalidates_election_cache(self):
        self._warm_turnout()
        self.client.delete(f"/api/v1/admin/candidates/{self.candidate.id}/")
        self.assertIsNone(caches["default"].get(election_turnout(self.election.id)))

    def test_candidate_reorder_invalidates_election_cache(self):
        second = make_candidate(self.election, full_name="Второй", order=1)
        self._warm_turnout()
        self.client.post(
            f"/api/v1/admin/elections/{self.election.id}/candidates/reorder/",
            {"ordered_ids": [str(second.id), str(self.candidate.id)]}, format="json",
        )
        self.assertIsNone(caches["default"].get(election_turnout(self.election.id)))

    def test_cancel_invalidates_election_cache(self):
        self._warm_turnout()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/api/v1/admin/elections/{self.election.id}/cancel/")
        self.assertIsNone(caches["default"].get(election_turnout(self.election.id)))


class VoteDecisionIgnoresCacheTest(ContractTestCase):
    """ТЗ п.22: решение о приёме голоса кэшу не доверяет."""

    def setUp(self):
        super().setUp()
        caches["default"].clear()
        self.uni = make_university()
        self.election = make_election(self.uni)
        self.candidate = make_candidate(self.election)
        self.student = Student.objects.create(
            university=self.uni, student_id="S-1", full_name="Тест", course=1
        )
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {create_student_token(self.student)}"}

    def test_stale_cached_election_does_not_allow_voting_after_finish(self):
        """Даже если в кэше лежат данные активных выборов, завершённые
        выборы обязаны отклонить голос: проверка идёт в транзакции."""
        caches["default"].set(
            election_public(self.election.id),
            {"status": Election.Status.ACTIVE, "title": "устаревшее"},
            timeout=300,
        )
        self.election.status = Election.Status.FINISHED
        self.election.save(update_fields=["status"])

        res = self.client.post(
            "/api/v1/voting/cast/",
            {"election_id": str(self.election.id), "candidate_id": str(self.candidate.id)},
            format="json", **self.headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "election_not_active")

    def test_stale_positive_vote_cache_does_not_block_first_vote(self):
        """Кэш статуса не участвует в решении о приёме голоса."""
        from apps.core.cache_keys import student_vote_status
        from apps.voting.models import Ballot, VoteRecord

        caches["default"].set(student_vote_status(self.student.id, self.election.id), True, 300)

        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(
                "/api/v1/voting/cast/",
                {"election_id": str(self.election.id), "candidate_id": str(self.candidate.id)},
                format="json", **self.headers,
            )
        self.assertEqual(res.status_code, 200, "кэш не должен решать, принимать ли голос")
        self.assertEqual(VoteRecord.objects.count(), 1)
        self.assertEqual(Ballot.objects.count(), 1)
