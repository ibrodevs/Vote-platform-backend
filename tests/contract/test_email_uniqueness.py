"""Case-insensitive уникальность email (ТЗ п.15).

Регистрация проверяла exists() перед INSERT — два параллельных запроса
проходили проверку одновременно. Гонка закрывается констрейнтом базы.
"""
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.students.models import Student

from .base import ContractTestCase
from .factories import make_university


class EmailUniquenessConstraintTest(TestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university()

    def _create(self, email, code):
        return Student.objects.create(
            university=self.uni, student_id=code, full_name="Тест", course=1, email=email
        )

    def test_exact_duplicate_rejected(self):
        self._create("dup@kstu.kg", "S-1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._create("dup@kstu.kg", "S-2")

    def test_case_insensitive_duplicate_rejected(self):
        """Главное требование: DUP@KSTU.KG и dup@kstu.kg — один и тот же адрес."""
        self._create("dup@kstu.kg", "S-1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._create("DUP@KSTU.KG", "S-2")

    def test_multiple_null_emails_allowed(self):
        """Студентов без email в базе много — они не должны конфликтовать."""
        self._create(None, "S-1")
        self._create(None, "S-2")
        self.assertEqual(Student.objects.filter(email__isnull=True).count(), 2)

    def test_multiple_empty_emails_allowed(self):
        self._create("", "S-1")
        self._create("", "S-2")
        self.assertEqual(Student.objects.filter(email="").count(), 2)

    def test_different_emails_allowed(self):
        self._create("a@kstu.kg", "S-1")
        self._create("b@kstu.kg", "S-2")
        self.assertEqual(Student.objects.count(), 2)


class RegistrationRaceTest(ContractTestCase):
    """API не должен отдавать 500 при срабатывании констрейнта."""

    def setUp(self):
        super().setUp()
        self.uni = make_university()
        self.payload = {
            "full_name": "Азамат Исаков",
            "university_id": str(self.uni.id),
            "course": 3,
            "group": "ПИ-1-21",
            "email": "race@kstu.kg",
            "password": "studentpass123",
        }

    def test_duplicate_registration_returns_400(self):
        first = self.client.post("/api/v1/auth/student/register/", self.payload, format="json")
        self.assertEqual(first.status_code, 201)
        second = self.client.post("/api/v1/auth/student/register/", self.payload, format="json")
        self.assertEqual(second.status_code, 400)
        self.assertErrorEnvelope(second, "email_already_exists")

    def test_duplicate_with_different_case_returns_400(self):
        self.client.post("/api/v1/auth/student/register/", self.payload, format="json")
        self.payload["email"] = "RACE@KSTU.KG"
        second = self.client.post("/api/v1/auth/student/register/", self.payload, format="json")
        self.assertEqual(second.status_code, 400)
        self.assertErrorEnvelope(second, "email_already_exists")

    def test_constraint_violation_is_not_a_500(self):
        """Если проверка exists() проиграет гонке, сработает констрейнт.

        Ответ обязан остаться тем же 400 email_already_exists, а не 500.
        Проверяется удалением проверки из кода через мок.
        """
        from unittest import mock

        self.client.post("/api/v1/auth/student/register/", self.payload, format="json")

        # Подменяется ТОЛЬКО проверка по email. Подменить Student.objects.filter
        # целиком нельзя: его использует Student.save() для отзыва токенов,
        # и мок сломал бы сам INSERT, а тест проверял бы не то.
        real_filter = Student.objects.filter

        def filter_without_email_check(*args, **kwargs):
            if "email__iexact" in kwargs:
                stub = mock.MagicMock()
                stub.exists.return_value = False
                return stub
            return real_filter(*args, **kwargs)

        with mock.patch.object(
            Student.objects, "filter", side_effect=filter_without_email_check
        ):
            res = self.client.post(
                "/api/v1/auth/student/register/", self.payload, format="json"
            )

        self.assertEqual(res.status_code, 400, f"вместо 400 получен {res.status_code}")
        self.assertErrorEnvelope(res, "email_already_exists")
        self.assertEqual(
            Student.objects.filter(email__iexact="race@kstu.kg").count(), 1,
            "констрейнт не дал создать второго студента",
        )
