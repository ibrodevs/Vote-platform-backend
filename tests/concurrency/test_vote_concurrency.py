"""Обязательные concurrency-тесты ТЗ п.72–75.

Каждый проверяет главный acceptance-критерий: после нагрузки в базе ровно
столько VoteRecord и Ballot, сколько голосов было реально принято, без дублей
и без частичных записей (ТЗ п.87).
"""
import threading
import time

from django.db import connection
from django.utils import timezone

from apps.elections.models import Election
from apps.elections.services import finish_election
from apps.voting.models import Ballot, VoteRecord
from apps.voting.services import AlreadyVotedError, ElectionNotActiveError, cast_secret_ballot

from tests.contract.factories import make_candidate, make_election, make_student, make_university

from .base import ConcurrencyTestCase


class SingleStudentManyRequestsTest(ConcurrencyTestCase):
    """ТЗ п.72: один студент, сотни параллельных попыток проголосовать."""

    ATTEMPTS = 100

    def setUp(self):
        super().setUp()
        self.uni = make_university()
        self.student = make_student(self.uni, student_id="S-1")
        self.election = make_election(self.uni)
        self.candidate = make_candidate(self.election)

    def test_single_student_many_requests(self):
        def attempt(_):
            return cast_secret_ballot(
                self.student, str(self.election.id), str(self.candidate.id)
            )

        results, errors = self.run_concurrently(attempt, self.ATTEMPTS)

        self.assertEqual(len(results), 1, f"успешных голосов должно быть ровно 1, получено {len(results)}")
        self.assertEqual(len(errors), self.ATTEMPTS - 1)
        self.assertTrue(
            all(isinstance(e, AlreadyVotedError) for e in errors),
            f"все отказы должны быть AlreadyVoted, получено: {{type(e).__name__ for e in errors}}",
        )
        self.assertVoteIntegrity(self.election, expected_votes=1)


class ManyStudentsParallelTest(ConcurrencyTestCase):
    """ТЗ п.73: 1000 уникальных студентов голосуют одновременно.

    Главное здесь — что они НЕ сериализуются через строку выборов.
    До этапа 2 каждый голос брал SELECT FOR UPDATE на Election.
    """

    STUDENTS = 1000
    CANDIDATES = 10

    def setUp(self):
        super().setUp()
        self.uni = make_university()
        self.election = make_election(self.uni)
        self.candidates = [
            make_candidate(self.election, full_name=f"Кандидат {i}", order=i)
            for i in range(self.CANDIDATES)
        ]
        self.students = [
            make_student(self.uni, student_id=f"S-{i:05d}") for i in range(self.STUDENTS)
        ]

    def test_many_students_vote_in_parallel(self):
        def attempt(index):
            student = self.students[index]
            candidate = self.candidates[index % self.CANDIDATES]
            return cast_secret_ballot(student, str(self.election.id), str(candidate.id))

        deadlocks_before = self.deadlock_count()
        results, errors = self.run_concurrently(attempt, self.STUDENTS, barrier=False)

        self.assertEqual(errors, [], f"ни один валидный голос не должен быть отклонён: {errors[:3]}")
        self.assertEqual(len(results), self.STUDENTS)
        self.assertVoteIntegrity(self.election, expected_votes=self.STUDENTS)

        # Сумма по кандидатам обязана сойтись с общим числом бюллетеней
        per_candidate = {
            c.id: Ballot.objects.filter(election=self.election, candidate=c).count()
            for c in self.candidates
        }
        self.assertEqual(sum(per_candidate.values()), self.STUDENTS)

        # ТЗ п.88: нештатных взаимоблокировок быть не должно
        self.assertEqual(
            self.deadlock_count(), deadlocks_before,
            "во время параллельного голосования возникли deadlock'и",
        )

    def test_no_duplicate_participation(self):
        def attempt(index):
            student = self.students[index % 50]
            candidate = self.candidates[index % self.CANDIDATES]
            return cast_secret_ballot(student, str(self.election.id), str(candidate.id))

        # 50 студентов, каждый пытается проголосовать по 4 раза
        self.run_concurrently(attempt, 200, barrier=False)

        self.assertEqual(VoteRecord.objects.filter(election=self.election).count(), 50)
        self.assertEqual(Ballot.objects.filter(election=self.election).count(), 50)


class VotesVersusFinishTest(ConcurrencyTestCase):
    """ТЗ п.74: голоса и завершение выборов идут параллельно.

    После коммита finish ни один новый голос приниматься не должен.
    Голоса, вошедшие в транзакцию до барьера, обязаны либо целиком
    закоммититься, либо целиком откатиться — без частичных записей.
    """

    STUDENTS = 300

    def setUp(self):
        super().setUp()
        self.uni = make_university()
        self.election = make_election(self.uni)
        self.candidate = make_candidate(self.election)
        self.students = [
            make_student(self.uni, student_id=f"S-{i:05d}") for i in range(self.STUDENTS)
        ]

    def test_votes_and_finish_are_serialized(self):
        finished_at = threading.Event()

        def finisher():
            try:
                time.sleep(0.05)  # дать части голосов стартовать
                finish_election(self.election)
                finished_at.set()
            finally:
                connection.close()

        thread = threading.Thread(target=finisher)

        def attempt(index):
            return cast_secret_ballot(
                self.students[index], str(self.election.id), str(self.candidate.id)
            )

        thread.start()
        results, errors = self.run_concurrently(attempt, self.STUDENTS, barrier=False)
        thread.join(60)

        self.assertTrue(finished_at.is_set(), "finish не завершился")
        self.election.refresh_from_db()
        self.assertEqual(self.election.status, Election.Status.FINISHED)

        # Все отказы — только из-за завершённых выборов, не из-за сбоев
        unexpected = [e for e in errors if not isinstance(e, ElectionNotActiveError)]
        self.assertEqual(unexpected, [], f"неожиданные ошибки: {unexpected[:3]}")

        # Никаких частичных записей: сколько приняли — столько и бюллетеней
        self.assertVoteIntegrity(self.election, expected_votes=len(results))

    def test_no_votes_accepted_after_finish_commits(self):
        finish_election(self.election)

        def attempt(index):
            return cast_secret_ballot(
                self.students[index], str(self.election.id), str(self.candidate.id)
            )

        results, errors = self.run_concurrently(attempt, 50, barrier=False)

        self.assertEqual(results, [], "после коммита finish ни один голос не должен быть принят")
        self.assertEqual(len(errors), 50)
        self.assertVoteIntegrity(self.election, expected_votes=0)


class SameStudentTwoCandidatesTest(ConcurrencyTestCase):
    """ТЗ п.75: один студент одновременно голосует за A и за B."""

    def setUp(self):
        super().setUp()
        self.uni = make_university()
        self.student = make_student(self.uni, student_id="S-1")
        self.election = make_election(self.uni)
        self.candidate_a = make_candidate(self.election, full_name="Кандидат A", order=0)
        self.candidate_b = make_candidate(self.election, full_name="Кандидат B", order=1)

    def test_same_student_two_candidates(self):
        def attempt(index):
            candidate = self.candidate_a if index % 2 == 0 else self.candidate_b
            return cast_secret_ballot(
                self.student, str(self.election.id), str(candidate.id)
            )

        results, errors = self.run_concurrently(attempt, 40)

        self.assertEqual(len(results), 1)
        self.assertVoteIntegrity(self.election, expected_votes=1)
        self.assertTrue(all(isinstance(e, AlreadyVotedError) for e in errors))

        # Бюллетень достался ровно одному кандидату
        a = Ballot.objects.filter(election=self.election, candidate=self.candidate_a).count()
        b = Ballot.objects.filter(election=self.election, candidate=self.candidate_b).count()
        self.assertEqual(a + b, 1, "нельзя получить два бюллетеня от одного студента")
