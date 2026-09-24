"""EXPLAIN (ANALYZE, BUFFERS) по горячим запросам (ТЗ п.14, 90).

Список запросов выведен из реального кода, а не придуман: путь голосования,
статус, доступные выборы, агрегация результатов, явка, аутентификация,
логин по email, identify и админский поиск.

    python manage.py explain_hot_queries
    python manage.py explain_hot_queries --format markdown > /tmp/plans.md
"""
import re

from django.core.management.base import BaseCommand
from django.db import connection

from apps.elections.models import Election
from apps.students.models import Student
from apps.universities.models import University


class Command(BaseCommand):
    help = "Показывает планы выполнения горячих запросов на текущих данных."

    def add_arguments(self, parser):
        parser.add_argument("--format", choices=["text", "markdown"], default="text")
        parser.add_argument("--only", help="Подстрока имени запроса для фильтрации.")

    def handle(self, *args, **opts):
        if connection.vendor != "postgresql":
            self.stderr.write("EXPLAIN ANALYZE имеет смысл только на PostgreSQL")
            return

        params = self._sample_params()
        if params is None:
            self.stderr.write(
                "Недостаточно данных. Сначала: python manage.py generate_test_data"
            )
            return

        self._print_volumes()

        for name, sql, args_ in self._queries(params):
            if opts["only"] and opts["only"].lower() not in name.lower():
                continue
            self._explain(name, sql, args_, opts["format"])

    # --- подготовка ---

    def _sample_params(self):
        election = (
            Election.objects.filter(status=Election.Status.FINISHED).first()
            or Election.objects.first()
        )
        student = Student.objects.filter(is_active=True).first()
        university = University.objects.first()
        if not (election and student and university):
            return None
        return {
            "election_id": str(election.id),
            "student_id": str(student.id),
            "university_id": str(university.id),
            "email": (student.email or "nobody@example.invalid"),
            "student_code": student.student_id,
        }

    def _print_volumes(self):
        self.stdout.write(self.style.MIGRATE_HEADING("Объём данных"))
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT relname, n_live_tup FROM pg_stat_user_tables
                WHERE n_live_tup > 0 ORDER BY n_live_tup DESC LIMIT 12
            """)
            for name, rows in cursor.fetchall():
                self.stdout.write(f"  {name:36} {rows:>10}")
        self.stdout.write("")

    # --- сами запросы ---

    def _queries(self, p):
        return [
            ("vote/ выбор выборов",
             "SELECT * FROM elections_election WHERE id = %s", [p["election_id"]]),

            ("vote/ проверка кандидата",
             "SELECT 1 FROM candidates_candidate WHERE election_id = %s LIMIT 1",
             [p["election_id"]]),

            ("vote status",
             "SELECT * FROM voting_voterecord WHERE election_id = %s AND student_id = %s",
             [p["election_id"], p["student_id"]]),

            ("available/ выборы, где студент голосовал",
             "SELECT election_id FROM voting_voterecord WHERE student_id = %s",
             [p["student_id"]]),

            ("available/ активные выборы вуза",
             """SELECT * FROM elections_election
                WHERE university_id = %s AND status = 'active'
                  AND starts_at <= now() AND ends_at >= now()
                ORDER BY ends_at""",
             [p["university_id"]]),

            ("results/ агрегация голосов",
             """SELECT candidate_id, COUNT(id) FROM voting_ballot
                WHERE election_id = %s GROUP BY candidate_id""",
             [p["election_id"]]),

            ("turnout/ явка",
             "SELECT COUNT(*) FROM voting_voterecord WHERE election_id = %s",
             [p["election_id"]]),

            ("turnout/ число избирателей",
             "SELECT COUNT(*) FROM students_student WHERE university_id = %s AND is_active",
             [p["university_id"]]),

            ("auth промах кэша",
             """SELECT id, student_id, university_id, full_name, is_active, auth_version
                FROM students_student WHERE id = %s""",
             [p["student_id"]]),

            ("login по email (iexact)",
             "SELECT * FROM students_student WHERE UPPER(email::text) = UPPER(%s) AND is_active",
             [p["email"]]),

            ("identify по коду студента (iexact)",
             """SELECT * FROM students_student
                WHERE university_id = %s AND UPPER(student_id::text) = UPPER(%s) AND is_active""",
             [p["university_id"], p["student_code"]]),

            ("admin поиск студентов (icontains)",
             """SELECT * FROM students_student
                WHERE UPPER(full_name::text) LIKE UPPER(%s)
                   OR UPPER(student_id::text) LIKE UPPER(%s)
                   OR UPPER(email::text) LIKE UPPER(%s)
                ORDER BY created_at DESC LIMIT 20""",
             ["%Асан%", "%Асан%", "%Асан%"]),

            ("admin список кандидатов",
             """SELECT * FROM candidates_candidate WHERE election_id = %s
                ORDER BY "order", created_at""",
             [p["election_id"]]),
        ]

    # --- вывод ---

    def _explain(self, name, sql, args, fmt):
        with connection.cursor() as cursor:
            cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS) {sql}", args)
            plan = [row[0] for row in cursor.fetchall()]

        scan = self._scan_kind(plan)
        timing = self._execution_time(plan)

        if fmt == "markdown":
            self.stdout.write(f"\n### {name}\n\n```sql\n{' '.join(sql.split())}\n```\n")
            self.stdout.write("```\n" + "\n".join(plan) + "\n```")
        else:
            marker = self.style.ERROR if "Seq Scan" in scan else self.style.SUCCESS
            self.stdout.write(self.style.MIGRATE_HEADING(name))
            self.stdout.write(f"  скан: {marker(scan)}   время: {timing}")
            for line in plan:
                self.stdout.write(f"    {line}")
            self.stdout.write("")

    @staticmethod
    def _scan_kind(plan):
        kinds = []
        for line in plan:
            for kind in ("Seq Scan", "Index Only Scan", "Index Scan", "Bitmap Heap Scan"):
                if kind in line and kind not in kinds:
                    kinds.append(kind)
        return ", ".join(kinds) or "—"

    @staticmethod
    def _execution_time(plan):
        for line in plan:
            match = re.search(r"Execution Time: ([\d.]+) ms", line)
            if match:
                return f"{match.group(1)} ms"
        return "—"
