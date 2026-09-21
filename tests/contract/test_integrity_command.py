"""Тесты команды verify_election_integrity (ТЗ п.87, 115)."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.voting.models import Ballot, VoteRecord

from .factories import make_candidate, make_election, make_student, make_university


def verify(**kwargs):
    out = StringIO()
    call_command("verify_election_integrity", stdout=out, stderr=StringIO(), **kwargs)
    return out.getvalue()


class IntegrityCommandTest(TestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university()
        self.election = make_election(self.uni)
        self.candidate = make_candidate(self.election)
        self.students = [
            make_student(self.uni, student_id=f"S-{i}") for i in range(5)
        ]

    def _cast(self, count):
        for student in self.students[:count]:
            VoteRecord.objects.create(election=self.election, student=student)
            Ballot.objects.create(election=self.election, candidate=self.candidate)

    def test_clean_data_passes(self):
        self._cast(3)
        self.assertIn("Целостность подтверждена", verify())

    def test_detects_missing_ballot(self):
        """Частично записанный голос — нарушение атомарности (ТЗ п.5)."""
        self._cast(3)
        Ballot.objects.first().delete()
        with self.assertRaises(CommandError):
            verify()

    def test_detects_orphan_ballot(self):
        self._cast(2)
        other = make_election(self.uni, title="Другие")
        foreign = make_candidate(other, full_name="Чужой")
        Ballot.objects.create(election=self.election, candidate=foreign)
        VoteRecord.objects.create(election=self.election, student=self.students[2])
        with self.assertRaises(CommandError):
            verify()

    def test_detects_foreign_university_vote(self):
        other_uni = make_university(code="other")
        outsider = make_student(other_uni, student_id="X-1")
        VoteRecord.objects.create(election=self.election, student=outsider)
        Ballot.objects.create(election=self.election, candidate=self.candidate)
        with self.assertRaises(CommandError):
            verify()

    def test_expected_votes_mismatch_fails(self):
        """Проверка после нагрузочного прогона: принято не столько, сколько ждали."""
        self._cast(3)
        with self.assertRaises(CommandError):
            verify(expected_votes=100)

    def test_expected_votes_match_passes(self):
        self._cast(3)
        self.assertIn("Целостность подтверждена", verify(expected_votes=3))

    def test_command_does_not_pair_student_with_candidate(self):
        """ТЗ п.115: команда не должна сопоставлять студента с кандидатом."""
        self._cast(3)
        output = verify()
        for student in self.students[:3]:
            self.assertNotIn(str(student.id), output)
        self.assertNotIn(str(self.candidate.id), output)

    def test_command_is_read_only(self):
        self._cast(3)
        before = (VoteRecord.objects.count(), Ballot.objects.count())
        verify()
        self.assertEqual((VoteRecord.objects.count(), Ballot.objects.count()), before)
