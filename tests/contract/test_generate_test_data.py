"""Тесты генератора синтетических данных (ТЗ п.78)."""
from io import StringIO

from django.core.management import call_command
from django.db.models import F
from django.test import TestCase

from apps.candidates.models import Candidate
from apps.elections.models import Election
from apps.students.models import Student
from apps.universities.models import University
from apps.voting.models import Ballot, VoteRecord


def generate(**kwargs):
    out = StringIO()
    call_command("generate_test_data", stdout=out, stderr=StringIO(), **kwargs)
    return out.getvalue()


class GenerateTestDataTest(TestCase):
    SMALL = dict(universities=2, students=40, elections=4,
                 candidates_per_election=3, vote_ratio=0.5)

    def test_creates_requested_volume(self):
        generate(**self.SMALL)
        self.assertEqual(University.objects.count(), 2)
        self.assertEqual(Student.objects.count(), 40)
        self.assertEqual(Election.objects.count(), 4)
        self.assertEqual(Candidate.objects.count(), 12)

    def test_vote_invariant_holds(self):
        """Генератор, ломающий 1:1, обесценил бы все проверки целостности."""
        generate(**self.SMALL)
        self.assertEqual(VoteRecord.objects.count(), Ballot.objects.count())
        self.assertGreater(VoteRecord.objects.count(), 0)

    def test_vote_invariant_holds_per_election(self):
        generate(**self.SMALL)
        for election in Election.objects.all():
            self.assertEqual(
                VoteRecord.objects.filter(election=election).count(),
                Ballot.objects.filter(election=election).count(),
                f"расхождение в выборах {election.title}",
            )

    def test_no_duplicate_participation(self):
        generate(**self.SMALL)
        pairs = VoteRecord.objects.values_list("election_id", "student_id")
        self.assertEqual(len(set(pairs)), len(pairs))

    def test_ballots_reference_own_election_candidates(self):
        generate(**self.SMALL)
        mismatched = Ballot.objects.exclude(
            candidate__election_id=F("election_id")
        ).count()
        self.assertEqual(mismatched, 0, "бюллетень указывает на кандидата чужих выборов")

    def test_no_real_personal_data(self):
        """Телефоны из невыдаваемого диапазона, email на .invalid (RFC 2606)."""
        generate(**self.SMALL)
        for student in Student.objects.all():
            self.assertTrue(student.email.endswith("@example.invalid"), student.email)
            self.assertTrue(student.phone_number.startswith("+9967770"), student.phone_number)

    def test_audit_finds_no_problems(self):
        generate(**self.SMALL)
        out = StringIO()
        call_command("audit_db_data", stdout=out, stderr=StringIO())
        self.assertIn("Проблем не найдено", out.getvalue())

    def test_clear_removes_only_synthetic(self):
        real_uni = University.objects.create(name="Настоящий", name_ky="Н", code="real-uni")
        Student.objects.create(university=real_uni, student_id="REAL-1",
                               full_name="Настоящий Студент", course=1)
        generate(**self.SMALL)
        generate(clear=True)

        self.assertEqual(University.objects.count(), 1)
        self.assertEqual(Student.objects.count(), 1)
        self.assertEqual(Student.objects.get().student_id, "REAL-1")

    def test_is_deterministic_for_same_seed(self):
        generate(**self.SMALL, seed=42)
        first = list(Student.objects.order_by("student_id").values_list("full_name", flat=True))
        generate(clear=True)
        generate(**self.SMALL, seed=42)
        second = list(Student.objects.order_by("student_id").values_list("full_name", flat=True))
        self.assertEqual(first, second)
