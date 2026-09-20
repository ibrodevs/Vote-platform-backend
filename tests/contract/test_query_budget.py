"""Бюджеты SQL-запросов на горячих endpoint'ах (ТЗ п.25, 26, 27, 48).

Главная проверка здесь — не абсолютное число запросов, а его НЕИЗМЕННОСТЬ
при росте данных. Endpoint, стоящий 12 запросов на пяти объектах и 62 на
пятидесяти, не масштабируется, каким бы быстрым он ни казался на демо-данных.
"""
from django.core.cache import caches
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.students.models import Student
from apps.students.services_auth import create_student_token
from apps.voting.models import Ballot, VoteRecord

from .base import ContractTestCase
from .factories import make_admin, make_candidate, make_election, make_student, make_university

SERVICE_MARKERS = ("SAVEPOINT", "RELEASE", "ROLLBACK", "pg_advisory", "BEGIN", "COMMIT")


def real_sql(captured):
    """Только содержательные запросы: служебная обвязка транзакций не в счёт."""
    return [q["sql"] for q in captured if not any(m in q["sql"] for m in SERVICE_MARKERS)]


class QueryBudgetMixin:
    def measure(self, fn):
        fn()  # прогрев кэша личности — меряем стоимость запроса, а не промаха
        with CaptureQueriesContext(connection) as ctx:
            response = fn()
        return len(real_sql(ctx.captured_queries)), response

    def assertBudget(self, fn, limit, label=""):
        count, response = self.measure(fn)
        self.assertLess(
            response.status_code, 400,
            f"{label}: endpoint вернул {response.status_code}",
        )
        self.assertLessEqual(count, limit, f"{label}: {count} SQL при бюджете {limit}")
        return count


class Dataset:
    """Набор данных заданного масштаба."""

    def __init__(self, code, n_elections, n_candidates, n_students, with_votes=True):
        self.uni = make_university(code=code)
        self.elections = []
        for i in range(n_elections):
            election = make_election(self.uni, title=f"Выборы {i}")
            for j in range(n_candidates):
                make_candidate(election, full_name=f"К{i}-{j}", order=j)
            self.elections.append(election)
        self.students = [
            make_student(self.uni, student_id=f"{code}-S{i:04d}") for i in range(n_students)
        ]
        if with_votes and self.students:
            target = self.elections[0]
            candidates = list(target.candidates.all())
            for index, student in enumerate(self.students[: max(1, n_students // 2)]):
                VoteRecord.objects.create(election=target, student=student)
                Ballot.objects.create(
                    election=target, candidate=candidates[index % len(candidates)]
                )

    @property
    def election(self):
        return self.elections[0]

    @property
    def student(self):
        return self.students[0]


class StudentEndpointBudgetTest(QueryBudgetMixin, ContractTestCase):
    def setUp(self):
        super().setUp()
        caches["default"].clear()
        self.small = Dataset("small", 2, 3, 5)
        self.large = Dataset("large", 5, 10, 20)

    def _headers(self, dataset):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_student_token(dataset.student)}"}

    def _available(self, dataset):
        return lambda: self.client.get(
            "/api/v1/elections/available/?all=true", **self._headers(dataset)
        )

    def _detail(self, dataset):
        return lambda: self.client.get(
            f"/api/v1/elections/{dataset.election.id}/", **self._headers(dataset)
        )

    def test_available_elections_budget(self):
        self.assertBudget(self._available(self.large), 4, "available elections")

    def test_available_elections_does_not_grow(self):
        small, _ = self.measure(self._available(self.small))
        large, _ = self.measure(self._available(self.large))
        self.assertEqual(
            small, large,
            f"число запросов выросло с {small} до {large} при увеличении данных",
        )

    def test_election_detail_budget(self):
        self.assertBudget(self._detail(self.large), 4, "election detail")

    def test_election_detail_does_not_grow(self):
        small, _ = self.measure(self._detail(self.small))
        large, _ = self.measure(self._detail(self.large))
        self.assertEqual(small, large)

    def test_recent_elections_does_not_grow(self):
        small, _ = self.measure(lambda: self.client.get("/api/v1/elections/recent/"))
        Dataset("extra", 6, 10, 2)
        large, _ = self.measure(lambda: self.client.get("/api/v1/elections/recent/"))
        self.assertEqual(small, large)


class AdminEndpointBudgetTest(QueryBudgetMixin, ContractTestCase):
    def setUp(self):
        super().setUp()
        caches["default"].clear()
        self.small = Dataset("small", 2, 3, 5)
        self.large = Dataset("large", 5, 10, 20)
        self.admin = make_admin(email="super@test.kg")
        self.as_admin(self.admin)

    def test_admin_elections_list_budget(self):
        self.assertBudget(
            lambda: self.client.get("/api/v1/admin/elections/"), 4, "admin elections"
        )

    def test_admin_elections_list_does_not_grow(self):
        """2 объекта на странице против всех 7 — число запросов одинаково.

        Тест осмыслен только при работающем page_size_query_param: до этапа 4
        параметр игнорировался, и оба вызова возвращали одно и то же.
        Проверяется явно.
        """
        few = self.client.get("/api/v1/admin/elections/?page_size=2")
        many = self.client.get("/api/v1/admin/elections/?page_size=100")
        self.assertLess(len(few.data["results"]), len(many.data["results"]),
                        "page_size не действует — тест ничего не проверяет")

        small, _ = self.measure(lambda: self.client.get("/api/v1/admin/elections/?page_size=2"))
        large, _ = self.measure(lambda: self.client.get("/api/v1/admin/elections/?page_size=100"))
        self.assertEqual(small, large)

    def test_admin_students_list_budget(self):
        self.assertBudget(
            lambda: self.client.get("/api/v1/admin/students/"), 4, "admin students"
        )

    def test_admin_students_list_does_not_grow(self):
        few = self.client.get("/api/v1/admin/students/?page_size=3")
        many = self.client.get("/api/v1/admin/students/?page_size=100")
        self.assertLess(len(few.data["results"]), len(many.data["results"]),
                        "page_size не действует — тест ничего не проверяет")

        small, _ = self.measure(lambda: self.client.get("/api/v1/admin/students/?page_size=3"))
        large, _ = self.measure(lambda: self.client.get("/api/v1/admin/students/?page_size=100"))
        self.assertEqual(small, large)

    def test_admin_universities_budget(self):
        self.assertBudget(
            lambda: self.client.get("/api/v1/admin/universities/"), 4, "admin universities"
        )

    def test_admin_universities_does_not_grow(self):
        for i in range(5):
            make_university(code=f"extra-{i}")
        few = self.client.get("/api/v1/admin/universities/?page_size=1")
        many = self.client.get("/api/v1/admin/universities/?page_size=100")
        self.assertLess(len(few.data["results"]), len(many.data["results"]),
                        "page_size не действует — тест ничего не проверяет")

        small, _ = self.measure(lambda: self.client.get("/api/v1/admin/universities/?page_size=1"))
        large, _ = self.measure(lambda: self.client.get("/api/v1/admin/universities/?page_size=100"))
        self.assertEqual(small, large)

    def test_admin_candidates_list_does_not_grow(self):
        small, _ = self.measure(
            lambda: self.client.get(f"/api/v1/admin/elections/{self.small.election.id}/candidates/")
        )
        large, _ = self.measure(
            lambda: self.client.get(f"/api/v1/admin/elections/{self.large.election.id}/candidates/")
        )
        self.assertEqual(small, large)


class ResultsBudgetTest(QueryBudgetMixin, ContractTestCase):
    """ТЗ п.27: результаты считаются одним агрегатом, а не 1+N подсчётами."""

    def setUp(self):
        super().setUp()
        caches["default"].clear()
        self.small = Dataset("small", 1, 3, 6)
        self.large = Dataset("large", 1, 25, 20)
        for dataset in (self.small, self.large):
            dataset.election.status = "finished"
            dataset.election.save(update_fields=["status"])
        self.admin = make_admin(email="super@test.kg")
        self.as_admin(self.admin)

    def _results(self, dataset):
        return lambda: self.client.get(f"/api/v1/admin/elections/{dataset.election.id}/results/")

    def _export(self, dataset):
        return lambda: self.client.post(
            f"/api/v1/admin/elections/{dataset.election.id}/results/export/"
        )

    def test_results_budget(self):
        self.assertBudget(self._results(self.large), 5, "results")

    def test_results_does_not_grow_with_candidates(self):
        small, _ = self.measure(self._results(self.small))
        large, _ = self.measure(self._results(self.large))
        self.assertEqual(
            small, large,
            f"подсчёт результатов вырос с {small} до {large} при 3 -> 25 кандидатах",
        )

    def test_export_budget(self):
        self.assertBudget(self._export(self.large), 5, "results export")

    def test_export_does_not_grow_with_candidates(self):
        small, _ = self.measure(self._export(self.small))
        large, _ = self.measure(self._export(self.large))
        self.assertEqual(small, large)

    def test_turnout_does_not_grow(self):
        small, _ = self.measure(
            lambda: self.client.get(f"/api/v1/admin/elections/{self.small.election.id}/turnout/")
        )
        large, _ = self.measure(
            lambda: self.client.get(f"/api/v1/admin/elections/{self.large.election.id}/turnout/")
        )
        self.assertEqual(small, large)
