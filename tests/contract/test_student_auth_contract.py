"""Contract-тесты студенческой аутентификации.

Endpoints смонтированы дважды: /api/v1/auth/student/... (использует фронтенд)
и /api/v1/students/auth/... (используют существующие тесты). Оба обязаны работать.
"""
import unittest
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from .base import ContractTestCase
from .factories import (
    DEFAULT_STUDENT_PASSWORD,
    make_auth_session,
    make_student,
    make_university,
    unknown_uuid,
)

STUDENT_KEYS = {"id", "student_id", "full_name", "email", "photo", "group", "faculty", "course"}
UNIVERSITY_KEYS = {"id", "name", "name_ky", "code"}


class StudentRegisterContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.payload = {
            "full_name": "Азамат Исаков",
            "university_id": str(self.uni.id),
            "faculty": "ФИТ",
            "course": 3,
            "group": "ПИ-1-21",
            "email": "azamat@kstu.kg",
            "password": DEFAULT_STUDENT_PASSWORD,
        }

    def test_register_returns_token_student_and_university(self):
        res = self.client.post("/api/v1/auth/student/register/", self.payload, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertKeys(res.data, {"student_token", "student", "university"})
        self.assertKeys(res.data["student"], STUDENT_KEYS)
        self.assertKeys(res.data["university"], UNIVERSITY_KEYS)
        self.assertTrue(res.data["student_token"])
        self.assertEqual(res.data["student"]["full_name"], "Азамат Исаков")
        self.assertEqual(res.data["student"]["course"], 3)
        self.assertIsNone(res.data["student"]["photo"])

    def test_register_duplicate_email_400(self):
        self.client.post("/api/v1/auth/student/register/", self.payload, format="json")
        res = self.client.post("/api/v1/auth/student/register/", self.payload, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "email_already_exists")

    def test_register_unknown_university_404(self):
        self.payload["university_id"] = unknown_uuid()
        res = self.client.post("/api/v1/auth/student/register/", self.payload, format="json")
        self.assertEqual(res.status_code, 404)
        self.assertErrorEnvelope(res, "university_not_found")

    def test_register_when_registration_closed_403(self):
        self.uni.is_registration_open = False
        self.uni.save(update_fields=["is_registration_open"])
        res = self.client.post("/api/v1/auth/student/register/", self.payload, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertErrorEnvelope(res, "registration_closed")

    def test_register_validation_error_envelope(self):
        self.payload["course"] = 99
        res = self.client.post("/api/v1/auth/student/register/", self.payload, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res)


class StudentLoginContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.student = make_student(
            self.uni,
            student_id="S-1001",
            email="azamat@kstu.kg",
            password=DEFAULT_STUDENT_PASSWORD,
        )

    def test_login_returns_same_shape_as_register(self):
        res = self.client.post(
            "/api/v1/auth/student/login/",
            {"email": "azamat@kstu.kg", "password": DEFAULT_STUDENT_PASSWORD},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertKeys(res.data, {"student_token", "student", "university"})
        self.assertKeys(res.data["student"], STUDENT_KEYS)
        self.assertKeys(res.data["university"], UNIVERSITY_KEYS)

    def test_login_wrong_password_400(self):
        res = self.client.post(
            "/api/v1/auth/student/login/",
            {"email": "azamat@kstu.kg", "password": "wrong-password"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "invalid_credentials")

    def test_login_unknown_email_400_same_code(self):
        res = self.client.post(
            "/api/v1/auth/student/login/",
            {"email": "nobody@kstu.kg", "password": DEFAULT_STUDENT_PASSWORD},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        # Тот же код, что и при неверном пароле — не раскрывает существование аккаунта
        self.assertErrorEnvelope(res, "invalid_credentials")

    def test_login_inactive_student_400(self):
        self.student.is_active = False
        self.student.save(update_fields=["is_active"])
        res = self.client.post(
            "/api/v1/auth/student/login/",
            {"email": "azamat@kstu.kg", "password": DEFAULT_STUDENT_PASSWORD},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "invalid_credentials")

    def test_both_auth_mount_points_work(self):
        body = {"email": "azamat@kstu.kg", "password": DEFAULT_STUDENT_PASSWORD}
        a = self.client.post("/api/v1/auth/student/login/", body, format="json")
        b = self.client.post("/api/v1/students/auth/login/", body, format="json")
        self.assertEqual(a.status_code, 200)
        self.assertEqual(b.status_code, 200)
        self.assertEqual(a.data["student"]["id"], b.data["student"]["id"])


class StudentProfileContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.student = make_student(self.uni, student_id="S-1001", email="a@kstu.kg")

    def test_profile_get_requires_student_token(self):
        res = self.client.get("/api/v1/auth/student/me/")
        self.assertEqual(res.status_code, 403)

    def test_profile_get_shape(self):
        self.as_student(self.student)
        res = self.client.get("/api/v1/auth/student/me/")
        self.assertEqual(res.status_code, 200)
        self.assertKeys(res.data, {"student", "university"})
        self.assertKeys(res.data["student"], STUDENT_KEYS)
        self.assertKeys(res.data["university"], UNIVERSITY_KEYS)

    def test_profile_patch_updates_full_name(self):
        self.as_student(self.student)
        res = self.client.patch(
            "/api/v1/auth/student/me/", {"full_name": "Новое Имя"}, format="multipart"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["student"]["full_name"], "Новое Имя")


class StudentOtpContractTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.student = make_student(
            self.uni, student_id="S-1001", phone_number="+996700000001"
        )
        self.identify_payload = {
            "university_code": "kstu",
            "student_id": "S-1001",
            "phone_number": "+996700000001",
        }

    def _identify(self):
        return self.client.post(
            "/api/v1/auth/student/identify/", self.identify_payload, format="json"
        )

    @override_settings(DEBUG=True)
    def test_identify_returns_request_id_and_expiry(self):
        res = self._identify()
        self.assertEqual(res.status_code, 200)
        self.assertKeys(res.data, {"request_id", "message", "expires_in_seconds", "demo_code"})
        self.assertGreater(res.data["expires_in_seconds"], 0)

    @override_settings(DEBUG=False)
    def test_identify_hides_demo_code_when_debug_off(self):
        res = self._identify()
        self.assertEqual(res.status_code, 200)
        self.assertKeys(res.data, {"request_id", "message", "expires_in_seconds"})

    def test_identify_unknown_university_404(self):
        self.identify_payload["university_code"] = "nope"
        res = self._identify()
        self.assertEqual(res.status_code, 404)
        self.assertErrorEnvelope(res, "university_not_found")

    def test_identify_unknown_student_404(self):
        self.identify_payload["student_id"] = "S-9999"
        res = self._identify()
        self.assertEqual(res.status_code, 404)
        self.assertErrorEnvelope(res, "student_not_found")

    def test_identify_phone_mismatch_400(self):
        self.identify_payload["phone_number"] = "+996700999999"
        res = self._identify()
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "phone_mismatch")

    @unittest.expectedFailure
    def test_verify_returns_student_token(self):
        """D-01: StudentVerifyView не возвращает Response → 500.

        Фронтенд (app/vote/[university_code]/verify/page.tsx) ожидает
        {student_token, student, university} и кладёт токен в sessionStorage.
        Снять expectedFailure после исправления на этапе 2.
        """
        session = make_auth_session(self.student, code="123456")
        res = self.client.post(
            "/api/v1/auth/student/verify/",
            {"request_id": str(session.id), "code": "123456"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertKeys(res.data, {"student_token", "student", "university"})

    def test_verify_invalid_session_400(self):
        res = self.client.post(
            "/api/v1/auth/student/verify/",
            {"request_id": unknown_uuid(), "code": "123456"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "invalid_session")

    def test_verify_already_used_session_400(self):
        session = make_auth_session(self.student, code="123456", is_verified=True)
        res = self.client.post(
            "/api/v1/auth/student/verify/",
            {"request_id": str(session.id), "code": "123456"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "already_verified")

    def test_verify_expired_code_400(self):
        session = make_auth_session(self.student, code="123456")
        session.expires_at = timezone.now() - timedelta(minutes=1)
        session.save(update_fields=["expires_at"])
        res = self.client.post(
            "/api/v1/auth/student/verify/",
            {"request_id": str(session.id), "code": "123456"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "code_expired")

    def test_verify_wrong_code_400(self):
        session = make_auth_session(self.student, code="123456")
        res = self.client.post(
            "/api/v1/auth/student/verify/",
            {"request_id": str(session.id), "code": "000000"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "invalid_code")

    def test_verify_too_many_attempts_429(self):
        session = make_auth_session(self.student, code="123456", attempts=5)
        res = self.client.post(
            "/api/v1/auth/student/verify/",
            {"request_id": str(session.id), "code": "123456"},
            format="json",
        )
        self.assertEqual(res.status_code, 429)
        self.assertErrorEnvelope(res, "too_many_attempts")
