"""Безопасность OTP (ТЗ п.34, 35, дефект D-05)."""
import threading
from datetime import timedelta

from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.students.models import Student, StudentAuthSession
from apps.students.services import send_student_otp

from .base import ContractTestCase
from .factories import make_university


class OtpStorageTest(ContractTestCase):
    """D-05: код больше не хранится и не логируется в открытом виде."""

    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.student = Student.objects.create(
            university=self.uni, student_id="S-1", full_name="Тест",
            course=1, phone_number="+996700000001",
        )

    def test_code_is_not_stored_in_plaintext(self):
        session, raw_code = send_student_otp(self.student, "+996700000001")
        session.refresh_from_db()
        self.assertNotIn(raw_code, session.code_hash)
        self.assertTrue(session.code_hash.startswith(("pbkdf2", "argon2", "bcrypt")),
                        session.code_hash[:20])

    def test_model_has_no_plaintext_field(self):
        fields = {f.name for f in StudentAuthSession._meta.get_fields()}
        self.assertNotIn("code", fields, "поле с открытым кодом должно быть удалено")

    def test_check_code_works(self):
        session, raw_code = send_student_otp(self.student, "+996700000001")
        self.assertTrue(session.check_code(raw_code))
        self.assertFalse(session.check_code("000000"))

    def test_str_reveals_neither_code_nor_hash(self):
        session, raw_code = send_student_otp(self.student, "+996700000001")
        text = str(session)
        self.assertNotIn(raw_code, text)
        self.assertNotIn(session.code_hash, text)
        self.assertNotIn(self.student.full_name, text)

    def test_code_is_not_logged(self):
        with self.assertLogs("apps.students.services", level="INFO") as captured:
            _, raw_code = send_student_otp(self.student, "+996700000001")
        blob = "\n".join(captured.output)
        self.assertNotIn(raw_code, blob, "код попал в лог")
        self.assertNotIn("+996700000001", blob, "полный телефон попал в лог")

    @override_settings(DEBUG=False)
    def test_identify_does_not_return_code_when_debug_off(self):
        res = self.client.post(
            "/api/v1/auth/student/identify/",
            {"university_code": "kstu", "student_id": "S-1",
             "phone_number": "+996700000001"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("demo_code", res.data)

    @override_settings(DEBUG=True)
    def test_identify_returns_code_in_debug(self):
        res = self.client.post(
            "/api/v1/auth/student/identify/",
            {"university_code": "kstu", "student_id": "S-1",
             "phone_number": "+996700000001"},
            format="json",
        )
        self.assertIn("demo_code", res.data)


class OtpVerifyFlowTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university(code="kstu")
        self.student = Student.objects.create(
            university=self.uni, student_id="S-1", full_name="Тест",
            course=1, phone_number="+996700000001",
        )
        self.session, self.raw_code = send_student_otp(self.student, "+996700000001")

    def _verify(self, code):
        return self.client.post(
            "/api/v1/auth/student/verify/",
            {"request_id": str(self.session.id), "code": code}, format="json",
        )

    def test_correct_code_issues_token(self):
        res = self._verify(self.raw_code)
        self.assertEqual(res.status_code, 200)
        self.assertIn("student_token", res.data)

    def test_wrong_code_rejected(self):
        res = self._verify("000000")
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res, "invalid_code")

    def test_attempts_increment_atomically(self):
        for _ in range(3):
            self._verify("000000")
        self.session.refresh_from_db()
        self.assertEqual(self.session.attempts, 3)

    def test_session_cannot_be_reused(self):
        self.assertEqual(self._verify(self.raw_code).status_code, 200)
        second = self._verify(self.raw_code)
        self.assertEqual(second.status_code, 400)
        self.assertErrorEnvelope(second, "already_verified")

    def test_expired_code_rejected(self):
        self.session.expires_at = timezone.now() - timedelta(minutes=1)
        self.session.save(update_fields=["expires_at"])
        self.assertEqual(self._verify(self.raw_code).status_code, 400)


class OtpConcurrencyTest(TransactionTestCase):
    """ТЗ п.35: параллельная проверка одного кода."""

    def setUp(self):
        super().setUp()
        if connection.vendor != "postgresql":
            self.skipTest("гонки проверяются на PostgreSQL")
        self.uni = make_university(code="kstu")
        self.student = Student.objects.create(
            university=self.uni, student_id="S-1", full_name="Тест",
            course=1, phone_number="+996700000001",
        )
        self.session, self.raw_code = send_student_otp(self.student, "+996700000001")

    def _run(self, fn, count):
        results, lock = [], threading.Lock()

        def worker():
            try:
                value = fn()
                with lock:
                    results.append(value)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(count)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(30)
        return results

    def test_one_otp_cannot_be_used_twice_concurrently(self):
        from rest_framework.test import APIClient

        def verify():
            return APIClient().post(
                "/api/v1/auth/student/verify/",
                {"request_id": str(self.session.id), "code": self.raw_code},
                format="json",
            ).status_code

        codes = self._run(verify, 10)
        self.assertEqual(
            codes.count(200), 1,
            f"один код выдал {codes.count(200)} успешных входов вместо одного",
        )

    def test_parallel_wrong_attempts_all_counted(self):
        """Неатомарный инкремент терял попытки — перебор обходил лимит."""
        from rest_framework.test import APIClient

        def verify():
            return APIClient().post(
                "/api/v1/auth/student/verify/",
                {"request_id": str(self.session.id), "code": "000000"},
                format="json",
            ).status_code

        self._run(verify, 5)
        self.session.refresh_from_db()
        self.assertEqual(self.session.attempts, 5, "часть попыток потеряна")
