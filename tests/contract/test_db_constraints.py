"""Тесты констрейнтов уровня БД (ТЗ п.6, 14, 16).

Защита от двойного голосования обязана обеспечиваться базой, а не Python-проверкой:
Python-проверка проигрывает гонке, констрейнт — нет.
"""
from datetime import timedelta

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from apps.elections.models import Election
from apps.voting.models import Ballot, VoteRecord

from .factories import make_candidate, make_election, make_student, make_university


class VoteRecordUniquenessTest(TestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university()
        self.student = make_student(self.uni, student_id="S-1")
        self.election = make_election(self.uni)

    def test_duplicate_vote_record_is_rejected_by_database(self):
        VoteRecord.objects.create(election=self.election, student=self.student)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                VoteRecord.objects.create(election=self.election, student=self.student)

    def test_same_student_in_different_elections_is_allowed(self):
        other = make_election(self.uni, title="Вторые выборы")
        VoteRecord.objects.create(election=self.election, student=self.student)
        VoteRecord.objects.create(election=other, student=self.student)
        self.assertEqual(VoteRecord.objects.filter(student=self.student).count(), 2)

    def test_unique_constraint_has_explicit_name(self):
        """Имя нужно, чтобы отличать причину IntegrityError от других нарушений."""
        names = {c.name for c in VoteRecord._meta.constraints}
        self.assertIn("uniq_voterecord_election_student", names)


class ElectionWindowConstraintTest(TestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university()

    def _create(self, starts_at, ends_at):
        return Election.objects.create(
            university=self.uni, title="X", title_ky="X",
            starts_at=starts_at, ends_at=ends_at,
        )

    def test_rejects_inverted_window(self):
        now = timezone.now()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._create(now + timedelta(hours=1), now)

    def test_rejects_zero_length_window(self):
        now = timezone.now()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._create(now, now)

    def test_accepts_valid_window(self):
        now = timezone.now()
        election = self._create(now, now + timedelta(hours=1))
        self.assertIsNotNone(election.pk)


class RedundantIndexTest(TestCase):
    def test_no_duplicate_index_over_unique_columns(self):
        """UNIQUE(election_id, student_id) уже создаёт индекс — второй лишний (ТЗ п.14)."""
        declared = [tuple(idx.fields) for idx in VoteRecord._meta.indexes]
        self.assertNotIn(
            ("election", "student"), declared,
            "индекс дублирует UNIQUE-констрейнт",
        )

    def test_database_has_no_redundant_index(self):
        if connection.vendor != "postgresql":
            self.skipTest("проверка плана индексов имеет смысл только на PostgreSQL")
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT indexdef FROM pg_indexes WHERE tablename = 'voting_voterecord'
            """)
            defs = [row[0] for row in cursor.fetchall()]
        over_pair = [
            d for d in defs
            if "election_id" in d and "student_id" in d and "USING btree" in d
        ]
        self.assertEqual(
            len(over_pair), 1,
            f"должен остаться ровно один индекс по (election_id, student_id): {over_pair}",
        )
