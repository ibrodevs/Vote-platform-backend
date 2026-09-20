"""Заголовки Cache-Control (ТЗ п.60, 96).

Без правильного заголовка промежуточный кэш вправе сохранить приватный
ответ и отдать его другому пользователю.
"""
from apps.core.cache_policy import PRIVATE_NO_STORE
from apps.students.models import Student
from apps.students.services_auth import create_student_token

from .base import ContractTestCase
from .factories import make_admin, make_candidate, make_election, make_faq, make_university


class PrivateResponsesTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.election = make_election(self.uni)
        make_candidate(self.election)
        self.student = Student.objects.create(
            university=self.uni, student_id="S-1", full_name="Тест", course=1
        )
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {create_student_token(self.student)}"}

    def _assert_private(self, response, label):
        header = response.get("Cache-Control", "")
        self.assertIn("private", header, f"{label}: {header!r}")
        self.assertIn("no-store", header, f"{label}: {header!r}")

    def test_vote_status_is_private(self):
        res = self.client.get(f"/api/v1/voting/status/{self.election.id}/", **self.headers)
        self._assert_private(res, "vote status")

    def test_vote_cast_is_private(self):
        res = self.client.post(
            "/api/v1/voting/cast/",
            {"election_id": str(self.election.id),
             "candidate_id": str(self.election.candidates.first().id)},
            format="json", **self.headers,
        )
        self._assert_private(res, "POST vote")

    def test_student_profile_is_private(self):
        res = self.client.get("/api/v1/auth/student/me/", **self.headers)
        self._assert_private(res, "profile")

    def test_available_elections_is_private(self):
        res = self.client.get("/api/v1/elections/available/", **self.headers)
        self._assert_private(res, "available elections")

    def test_admin_endpoints_are_private(self):
        admin = make_admin(email="super@test.kg")
        self.as_admin(admin)
        for url in ("/api/v1/admin/elections/", "/api/v1/admin/students/",
                    "/api/v1/admin/universities/"):
            with self.subTest(url=url):
                self._assert_private(self.client.get(url), url)

    def test_admin_login_is_private(self):
        res = self.client.post(
            "/api/v1/auth/admin/login/",
            {"email": "nobody@test.kg", "password": "x"}, format="json",
        )
        self._assert_private(res, "admin login")


class PublicResponsesTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        make_election(self.uni)
        make_faq()

    def test_public_lists_are_cacheable(self):
        for url in ("/api/v1/universities/", "/api/v1/faqs/",
                    "/api/v1/news/", "/api/v1/elections/recent/"):
            with self.subTest(url=url):
                header = self.client.get(url).get("Cache-Control", "")
                self.assertIn("public", header, f"{url}: {header!r}")

    def test_public_path_with_token_becomes_private(self):
        """Запрос с авторизацией персонализирован, даже если путь публичный."""
        student = Student.objects.create(
            university=self.uni, student_id="S-1", full_name="Тест", course=1
        )
        headers = {"HTTP_AUTHORIZATION": f"Bearer {create_student_token(student)}"}
        header = self.client.get("/api/v1/universities/", **headers).get("Cache-Control", "")
        self.assertIn("private", header, header)

    def test_unknown_path_defaults_to_private(self):
        """Безопасное значение по умолчанию: публичным надо стать явно."""
        header = self.client.get("/api/v1/elections/").get("Cache-Control", "")
        self.assertEqual(header, PRIVATE_NO_STORE)
