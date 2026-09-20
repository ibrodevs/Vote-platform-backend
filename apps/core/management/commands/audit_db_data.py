"""Аудит данных перед миграцией на PostgreSQL и перед добавлением констрейнтов.

ТЗ п.15, 54, 55. Команда СТРОГО read-only: она находит и печатает проблемы,
но никогда ничего не удаляет, не сливает и не правит. Решение о том, что делать
с найденным, принимает человек.

    python manage.py audit_db_data
    python manage.py audit_db_data --fail-on-issues   # ненулевой код возврата в CI
"""
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, F

from apps.accounts.models import AdminUser
from apps.candidates.models import Candidate
from apps.content.models import FAQItem, NewsArticle, StaticPage
from apps.elections.models import Election
from apps.students.models import Student, UploadBatch
from apps.universities.models import Faculty, University
from apps.voting.models import Ballot, VoteRecord


class Command(BaseCommand):
    help = "Проверяет данные перед миграцией на PostgreSQL. Ничего не изменяет."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail-on-issues",
            action="store_true",
            help="Завершиться с ошибкой, если найдены проблемы (для CI и pre-migration gate).",
        )

    def handle(self, *args, **options):
        findings = {}

        for name, check in (
            ("duplicate_emails", self.check_duplicate_emails),
            ("duplicate_student_ids", self.check_duplicate_student_ids),
            ("invalid_election_window", self.check_invalid_election_window),
            ("duplicate_vote_records", self.check_duplicate_vote_records),
            ("orphan_ballots", self.check_orphan_ballots),
            ("candidate_university_mismatch", self.check_candidate_university_mismatch),
        ):
            result = check()
            if result:
                findings[name] = result

        self._print_row_counts()

        if findings:
            self._print_findings(findings)
        else:
            self.stdout.write(self.style.SUCCESS("\nПроблем не найдено."))

        if findings and options["fail_on_issues"]:
            raise CommandError(
                f"Найдено проблем: {sum(len(v) for v in findings.values())}. "
                "Миграцию запускать нельзя, пока они не разобраны вручную."
            )

    # --- проверки ---

    def check_duplicate_emails(self):
        """Дубликаты email без учёта регистра.

        Блокируют case-insensitive UNIQUE, который добавляется на этапе 5 (ТЗ п.15).
        Пустые и NULL email дубликатами не считаются — констрейнт их не затронет.
        """
        buckets = defaultdict(list)
        rows = Student.objects.exclude(email__isnull=True).exclude(email="").values(
            "id", "email", "student_id", "university__code"
        )
        for row in rows:
            buckets[row["email"].strip().lower()].append(row)
        return [
            {"email": email, "students": items}
            for email, items in sorted(buckets.items())
            if len(items) > 1
        ]

    def check_duplicate_student_ids(self):
        """Дубликаты (university_id, student_id) внутри одного вуза."""
        dupes = (
            Student.objects.exclude(student_id="")
            .values("university_id", "student_id")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
            .order_by("student_id")
        )
        return [
            {
                "university_id": str(d["university_id"]),
                "student_id": d["student_id"],
                "count": d["n"],
            }
            for d in dupes
        ]

    def check_invalid_election_window(self):
        """starts_at >= ends_at — заблокирует CHECK-констрейнт этапа 2 (ТЗ п.16)."""
        rows = Election.objects.filter(starts_at__gte=F("ends_at")).values(
            "id", "title", "starts_at", "ends_at"
        )
        return [
            {
                "election_id": str(r["id"]),
                "title": r["title"],
                "starts_at": r["starts_at"].isoformat(),
                "ends_at": r["ends_at"].isoformat(),
            }
            for r in rows
        ]

    def check_duplicate_vote_records(self):
        """Дубликаты (election_id, student_id) — нарушение главного инварианта (ТЗ п.6)."""
        dupes = (
            VoteRecord.objects.values("election_id", "student_id")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        return [
            {
                "election_id": str(d["election_id"]),
                "student_id": str(d["student_id"]),
                "count": d["n"],
            }
            for d in dupes
        ]

    def check_orphan_ballots(self):
        """Ballot, чей кандидат принадлежит другим выборам."""
        rows = Ballot.objects.exclude(candidate__election_id=F("election_id")).values(
            "id", "election_id", "candidate_id", "candidate__election_id"
        )
        return [
            {
                "ballot_id": str(r["id"]),
                "ballot_election_id": str(r["election_id"]),
                "candidate_election_id": str(r["candidate__election_id"]),
            }
            for r in rows
        ]

    def check_candidate_university_mismatch(self):
        """Кандидат числится не за тем вузом, что проводит выборы."""
        rows = Candidate.objects.exclude(
            university_id=F("election__university_id")
        ).values("id", "full_name", "university_id", "election__university_id")
        return [
            {
                "candidate_id": str(r["id"]),
                "full_name": r["full_name"],
                "candidate_university_id": str(r["university_id"]),
                "election_university_id": str(r["election__university_id"]),
            }
            for r in rows
        ]

    # --- вывод ---

    def _print_row_counts(self):
        """Счётчики для сверки до и после переноса (ТЗ п.55)."""
        counts = {
            "universities": University.objects.count(),
            "faculties": Faculty.objects.count(),
            "admin_users": AdminUser.objects.count(),
            "students": Student.objects.count(),
            "upload_batches": UploadBatch.objects.count(),
            "elections": Election.objects.count(),
            "candidates": Candidate.objects.count(),
            "vote_records": VoteRecord.objects.count(),
            "ballots": Ballot.objects.count(),
            "news_articles": NewsArticle.objects.count(),
            "faq_items": FAQItem.objects.count(),
            "static_pages": StaticPage.objects.count(),
        }
        self.stdout.write(self.style.MIGRATE_HEADING("row_counts"))
        width = max(len(k) for k in counts)
        for name, value in counts.items():
            self.stdout.write(f"  {name.ljust(width)}  {value}")
        self.stdout.write(
            "\n  Эти числа обязаны совпасть после переноса в PostgreSQL.\n"
            "  Любое расхождение — стоп-сигнал, см. docs/SQLITE_TO_POSTGRES.md"
        )

    def _print_findings(self, findings):
        total = sum(len(v) for v in findings.values())
        self.stdout.write(self.style.ERROR(f"\nНайдено проблем: {total}"))

        for name, items in findings.items():
            self.stdout.write(self.style.WARNING(f"\n{name} ({len(items)})"))
            for item in items[:50]:
                self.stdout.write(f"  {item}")
            if len(items) > 50:
                self.stdout.write(f"  ... и ещё {len(items) - 50}")

        self.stdout.write(
            self.style.NOTICE(
                "\nКоманда ничего не изменила. Разберите находки вручную:\n"
                "  duplicate_emails              -> решить, какой аккаунт оставить (этап 5, ТЗ п.15)\n"
                "  duplicate_student_ids         -> исправить данные вуза\n"
                "  invalid_election_window       -> поправить даты до CHECK-констрейнта (ТЗ п.16)\n"
                "  duplicate_vote_records        -> нарушен инвариант голосования, разбирать вручную\n"
                "  orphan_ballots                -> бюллетень указывает на кандидата чужих выборов\n"
                "  candidate_university_mismatch -> привести university кандидата к вузу выборов\n"
            )
        )
