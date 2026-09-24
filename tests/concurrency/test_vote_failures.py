"""Failure-тесты голосования (ТЗ п.76).

Главное правило: если транзакция не закоммичена — успех не возвращается;
если закоммичена — данные корректны. Промежуточных состояний нет.
"""
from unittest import mock

from django.db import DatabaseError, IntegrityError, connection

from apps.voting.models import Ballot, VoteRecord
from apps.voting.services import AlreadyVotedError, cast_secret_ballot

from tests.contract.factories import make_candidate, make_election, make_student, make_university

from .base import ConcurrencyTestCase


class VoteFailureTest(ConcurrencyTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university()
        self.student = make_student(self.uni, student_id="S-1")
        self.other = make_student(self.uni, student_id="S-2")
        self.election = make_election(self.uni)
        self.candidate = make_candidate(self.election)

    def _cast(self, student=None):
        return cast_secret_ballot(
            student or self.student, str(self.election.id), str(self.candidate.id)
        )

    def test_exception_between_record_and_ballot_rolls_back_both(self):
        """Исключение после VoteRecord, до Ballot — не остаётся ни одной строки."""
        with mock.patch.object(
            Ballot.objects, "create", side_effect=RuntimeError("сбой после VoteRecord")
        ):
            with self.assertRaises(RuntimeError):
                self._cast()

        self.assertEqual(VoteRecord.objects.count(), 0, "VoteRecord без Ballot после отката")
        self.assertEqual(Ballot.objects.count(), 0)

    def test_database_error_on_ballot_rolls_back_vote_record(self):
        with mock.patch.object(
            Ballot.objects, "create", side_effect=DatabaseError("соединение потеряно")
        ):
            with self.assertRaises(DatabaseError):
                self._cast()

        self.assertEqual(VoteRecord.objects.count(), 0)
        self.assertEqual(Ballot.objects.count(), 0)

    def test_duplicate_creates_no_ballot(self):
        """ТЗ п.10: после нарушения UNIQUE бюллетень создаваться не должен."""
        self._cast()
        with self.assertRaises(AlreadyVotedError):
            self._cast()

        self.assertEqual(VoteRecord.objects.filter(election=self.election).count(), 1)
        self.assertEqual(Ballot.objects.filter(election=self.election).count(), 1)

    def test_connection_usable_after_integrity_error(self):
        """ТЗ п.10: транзакция не должна остаться в broken state.

        Без savepoint вокруг INSERT следующий же SQL падал бы
        с InFailedSqlTransaction.
        """
        self._cast()
        with self.assertRaises(AlreadyVotedError):
            self._cast()

        # Соединение обязано остаться рабочим
        self.assertEqual(VoteRecord.objects.count(), 1)
        self.assertTrue(self._cast(student=self.other))
        self.assertVoteIntegrity(self.election, expected_votes=2)

    def test_non_duplicate_integrity_error_is_not_masked(self):
        """Нарушение другого констрейнта не должно превратиться в AlreadyVoted.

        Иначе настоящая ошибка была бы скрыта и от разработчика, и от студента.
        """
        with mock.patch.object(
            VoteRecord.objects, "create",
            side_effect=IntegrityError('violates foreign key constraint "some_other_fk"'),
        ):
            with self.assertRaises(IntegrityError):
                self._cast()

        self.assertEqual(Ballot.objects.count(), 0)

    def test_redis_unavailable_does_not_block_voting(self):
        """ТЗ п.20: Redis не является точкой отказа для голосования."""
        import redis

        with mock.patch(
            "redis.Redis.execute_command",
            side_effect=redis.ConnectionError("Redis недоступен"),
        ):
            self.assertTrue(self._cast())

        self.assertVoteIntegrity(self.election, expected_votes=1)

    def test_no_orphan_ballot_after_repeated_failures(self):
        """Серия сбоев не должна накапливать бюллетени без записей об участии."""
        for _ in range(5):
            with mock.patch.object(
                Ballot.objects, "create", side_effect=RuntimeError("сбой")
            ):
                with self.assertRaises(RuntimeError):
                    self._cast()

        self.assertEqual(VoteRecord.objects.count(), 0)
        self.assertEqual(Ballot.objects.count(), 0)
        self.assertTrue(self._cast())
        self.assertVoteIntegrity(self.election, expected_votes=1)
