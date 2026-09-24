"""Бюджет SQL-запросов на горячих endpoint'ах (ТЗ п.48).

Требование ТЗ: O(1) обращений к базе относительно количества объектов.
Эти тесты фиксируют текущие числа — при их росте прогон падает,
и регрессия видна сразу, а не на нагрузочном тесте.
"""
from django.core.cache import caches
from django.test.utils import CaptureQueriesContext
from django.db import connection

from apps.students.models import Student
from apps.students.services_auth import create_student_token

from .base import ContractTestCase
from .factories import make_candidate, make_election, make_student, make_university


def real_sql(queries):
    """Оставляет только содержательные запросы.

    SAVEPOINT/RELEASE — служебная обвязка транзакций, а не обращения к данным;
    в тестах их порождает сам TestCase. Advisory-лок есть только на PostgreSQL,
    поэтому включать его в бюджет значило бы получить разные числа на разных СУБД.
    """
    skip = ("SAVEPOINT", "RELEASE", "ROLLBACK", "pg_advisory")
    return [
        q["sql"] for q in queries
        if not any(marker in q["sql"] for marker in skip)
    ]


class VoteQueryBudgetTest(ContractTestCase):
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
        # Прогрев кэша личности: измеряем стоимость запроса, а не промаха
        self.client.get("/api/v1/voting/status/%s/" % self.election.id, **self.headers)

    def _cast(self):
        return self.client.post(
            "/api/v1/voting/cast/",
            {"election_id": str(self.election.id), "candidate_id": str(self.candidate.id)},
            format="json",
            **self.headers,
        )

    def test_cast_vote_costs_four_statements(self):
        """SELECT выборов, EXISTS кандидата, INSERT VoteRecord, INSERT Ballot.

        Ноль запросов на аутентификацию — личность берётся из кэша.
        """
        with CaptureQueriesContext(connection) as ctx:
            res = self._cast()
        self.assertEqual(res.status_code, 200)

        statements = real_sql(ctx.captured_queries)
        self.assertEqual(len(statements), 4, "\n".join(statements))
        self.assertEqual(sum("students_student" in s for s in statements), 0,
                         "аутентификация не должна обращаться к таблице студентов")

    def test_cast_vote_query_count_does_not_grow_with_candidates(self):
        """Ключевое свойство: стоимость голоса не зависит от размера выборов."""
        for i in range(30):
            make_candidate(self.election, full_name=f"Кандидат {i}", order=i + 1)
        for i in range(50):
            make_student(self.uni, student_id=f"S-extra-{i}")

        with CaptureQueriesContext(connection) as ctx:
            res = self._cast()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(real_sql(ctx.captured_queries)), 4)

    def test_vote_status_query_count(self):
        with self.assertNumQueries(1):
            res = self.client.get(f"/api/v1/voting/status/{self.election.id}/", **self.headers)
        self.assertEqual(res.status_code, 200)

    def test_vote_status_makes_no_auth_query_on_cache_hit(self):
        """Единственный запрос — поиск VoteRecord; на аутентификацию SQL не тратится."""
        with self.assertNumQueries(1):
            self.client.get(f"/api/v1/voting/status/{self.election.id}/", **self.headers)
