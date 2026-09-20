"""Ограничение размера страницы (ТЗ п.93).

Админские списки не должны позволять выгрузить всю таблицу одним запросом:
это и нагрузка на базу, и выгрузка персональных данных пачкой.
"""
from apps.core.pagination import DefaultPagination

from .base import ContractTestCase
from .factories import make_admin, make_student, make_university


class PaginationLimitTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university()
        for i in range(30):
            make_student(self.uni, student_id=f"S-{i:04d}")
        self.admin = make_admin(email="super@test.kg")
        self.as_admin(self.admin)

    def test_default_page_size(self):
        res = self.client.get("/api/v1/admin/students/")
        self.assertEqual(len(res.data["results"]), 20)
        self.assertEqual(res.data["count"], 30)

    def test_client_can_reduce_page_size(self):
        res = self.client.get("/api/v1/admin/students/?page_size=5")
        self.assertEqual(len(res.data["results"]), 5)

    def test_page_size_is_capped(self):
        """Запрос гигантской страницы не выгружает всё — он усекается до потолка."""
        res = self.client.get("/api/v1/admin/students/?page_size=1000000")
        self.assertEqual(res.status_code, 200)
        self.assertLessEqual(len(res.data["results"]), DefaultPagination.max_page_size)

    def test_max_page_size_is_configured(self):
        self.assertIsNotNone(DefaultPagination.max_page_size)
        self.assertLessEqual(DefaultPagination.max_page_size, 500)

    def test_paginated_admin_lists_all_respect_cap(self):
        for url in (
            "/api/v1/admin/students/",
            "/api/v1/admin/elections/",
            "/api/v1/admin/universities/",
            "/api/v1/auth/admin/users/",
            "/api/v1/auth/admin/logs/",
        ):
            with self.subTest(url=url):
                res = self.client.get(f"{url}?page_size=1000000")
                self.assertEqual(res.status_code, 200)
                self.assertLessEqual(
                    len(res.data["results"]), DefaultPagination.max_page_size
                )
