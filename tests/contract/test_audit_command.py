"""Тесты команды audit_db_data.

Команда проверяет данные ПЕРЕД миграцией на PostgreSQL и перед добавлением
констрейнтов на этапах 2 и 5. Она обязана быть строго read-only (ТЗ п.15, 54, 55):
находки печатаются с инструкцией, но ничего не удаляется и не сливается.
"""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.candidates.models import Candidate
from apps.elections.models import Election
from apps.students.models import Student
from apps.voting.models import Ballot, VoteRecord

from .factories import (
    make_candidate,
    make_election,
    make_student,
    make_university,
)


def run_audit(**kwargs):
    out = StringIO()
    call_command("audit_db_data", stdout=out, stderr=StringIO(), **kwargs)
    return out.getvalue()


class AuditCommandTest(TestCase):
    def test_clean_database_reports_no_issues(self):
        uni = make_university()
        make_student(uni, student_id="S-1", email="a@kstu.kg")
        output = run_audit()
        self.assertIn("Проблем не найдено", output)

    def test_reports_duplicate_emails_case_insensitively(self):
        uni = make_university()
        make_student(uni, student_id="S-1", email="Dup@Kstu.kg")
        make_student(uni, student_id="S-2", email="dup@kstu.kg")
        output = run_audit()
        self.assertIn("duplicate_emails", output)
        self.assertIn("dup@kstu.kg", output)

    def test_empty_emails_are_not_duplicates(self):
        """NULL/'' в email — не дубликаты, будущий UNIQUE их не затронет."""
        uni = make_university()
        make_student(uni, student_id="S-1", email=None)
        make_student(uni, student_id="S-2", email=None)
        output = run_audit()
        self.assertNotIn("duplicate_emails", output)

    def test_reports_duplicate_student_ids_within_university(self):
        uni = make_university()
        make_student(uni, student_id="S-DUP")
        make_student(uni, student_id="S-DUP")
        output = run_audit()
        self.assertIn("duplicate_student_ids", output)
        self.assertIn("S-DUP", output)

    def test_same_student_id_in_different_universities_is_fine(self):
        a = make_university(code="a")
        b = make_university(code="b")
        make_student(a, student_id="S-1")
        make_student(b, student_id="S-1")
        output = run_audit()
        self.assertNotIn("duplicate_student_ids", output)

    def test_reports_candidate_university_mismatch(self):
        uni = make_university(code="a")
        other = make_university(code="b")
        election = make_election(uni)
        candidate = make_candidate(election)
        Candidate.objects.filter(id=candidate.id).update(university=other)
        output = run_audit()
        self.assertIn("candidate_university_mismatch", output)

    def test_reports_orphan_ballots(self):
        """Ballot, чей кандидат принадлежит другим выборам."""
        uni = make_university()
        election = make_election(uni)
        other_election = make_election(uni, title="Другие")
        foreign_candidate = make_candidate(other_election)
        Ballot.objects.create(election=election, candidate=foreign_candidate)
        output = run_audit()
        self.assertIn("orphan_ballots", output)

    def test_prints_row_counts_for_reconciliation(self):
        """Счётчики нужны для сверки до и после переноса (ТЗ п.55)."""
        uni = make_university()
        make_student(uni, student_id="S-1")
        output = run_audit()
        self.assertIn("row_counts", output)
        self.assertIn("students", output)
        self.assertIn("vote_records", output)
        self.assertIn("ballots", output)

    def test_command_is_read_only(self):
        uni = make_university()
        make_student(uni, student_id="S-1", email="Dup@Kstu.kg")
        make_student(uni, student_id="S-2", email="dup@kstu.kg")
        before = (
            Student.objects.count(),
            Election.objects.count(),
            Candidate.objects.count(),
            VoteRecord.objects.count(),
            Ballot.objects.count(),
        )
        run_audit()
        after = (
            Student.objects.count(),
            Election.objects.count(),
            Candidate.objects.count(),
            VoteRecord.objects.count(),
            Ballot.objects.count(),
        )
        self.assertEqual(before, after, "команда аудита не должна ничего менять")

    def test_fail_on_issues_flag_raises(self):
        from django.core.management.base import CommandError

        uni = make_university()
        make_student(uni, student_id="S-1", email="Dup@Kstu.kg")
        make_student(uni, student_id="S-2", email="dup@kstu.kg")
        with self.assertRaises(CommandError):
            run_audit(fail_on_issues=True)

    def test_fail_on_issues_flag_passes_on_clean_db(self):
        make_university()
        output = run_audit(fail_on_issues=True)
        self.assertIn("Проблем не найдено", output)


class AuditInvalidWindowTest(TransactionTestCase):
    """Отдельный класс: тесту нужен DDL, а внутри транзакции TestCase
    ALTER TABLE падает на отложенных FK-триггерах PostgreSQL."""

    def test_reports_invalid_election_window(self):
        """Аудит ловит starts_at >= ends_at.

        С этапа 2 такие данные запрещены CHECK-констрейнтом, поэтому воспроизвести
        их можно только временно сняв констрейнт. Проверка остаётся нужной: она
        существует ровно для баз, где констрейнта ещё нет — например для живого
        SQLite-деплоя до миграции (ТЗ п.16, 54).
        """
        from django.db import connection

        constraint = next(
            c for c in Election._meta.constraints
            if c.name == "election_starts_before_ends"
        )
        uni = make_university()
        now = timezone.now()

        with connection.schema_editor(atomic=False) as editor:
            editor.remove_constraint(Election, constraint)
        try:
            make_election(uni, starts_at=now + timedelta(hours=2), ends_at=now)
            output = run_audit()
            self.assertIn("invalid_election_window", output)
        finally:
            Election.objects.all().delete()
            with connection.schema_editor(atomic=False) as editor:
                editor.add_constraint(Election, constraint)
