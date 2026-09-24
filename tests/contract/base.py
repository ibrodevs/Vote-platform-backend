"""База для contract-тестов: клиент, аутентификация, ассерты формы ответа.

Contract-тесты фиксируют ТЕКУЩЕЕ поведение API, чтобы последующие этапы
оптимизации доказуемо не ломали фронтенд (ТЗ п.2, 49, 50).
"""
from django.test import TestCase
from rest_framework.test import APIClient

from .factories import DEFAULT_ADMIN_PASSWORD, student_token


class ContractTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    # --- аутентификация ---

    def as_student(self, student):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {student_token(student)}")

    def as_admin(self, admin, password=DEFAULT_ADMIN_PASSWORD):
        res = self.client.post(
            "/api/v1/auth/admin/login/",
            {"email": admin.email, "password": password},
            format="json",
        )
        assert res.status_code == 200, f"admin login failed: {res.status_code} {res.data}"
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
        return res.data

    def as_anonymous(self):
        self.client.credentials()

    # --- ассерты формы ответа ---

    def assertErrorEnvelope(self, response, code=None):
        """Конверт {"error": {"code", "message", "details"}} — контракт lib/api.ts."""
        self.assertIn("error", response.data, f"нет конверта error: {response.data}")
        err = response.data["error"]
        self.assertIn("code", err)
        self.assertIn("message", err)
        self.assertTrue(err["message"], "message не должен быть пустым")
        if code is not None:
            self.assertEqual(err["code"], code)
        return err

    def assertKeys(self, payload, expected):
        """Точное совпадение набора ключей: ловит и пропажу, и появление поля."""
        self.assertEqual(set(payload.keys()), set(expected))

    def assertPaginated(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertKeys(response.data, {"count", "next", "previous", "results"})
        return response.data["results"]
