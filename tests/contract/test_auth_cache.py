"""Тесты Redis-first аутентификации (ТЗ п.18, 20, 65).

Главная цель этапа 3: при 40k RPS нельзя делать SELECT Student на каждый
запрос. Здесь это проверяется числом запросов, а не рассуждением.
"""
import logging
from unittest import mock

from django.contrib.auth.hashers import make_password
from django.core.cache import caches
from django.test import override_settings

from apps.core.authentication import CombinedJWTAuthentication
from apps.core.cache_keys import student_principal
from apps.core.principals import StudentPrincipal
from apps.students.models import Student
from apps.students.services_auth import create_student_token

from .base import ContractTestCase
from .factories import make_candidate, make_election, make_university


class AuthQueryBudgetTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        caches["default"].clear()
        self.uni = make_university()
        self.student = Student.objects.create(
            university=self.uni, student_id="S-1", full_name="Тест",
            course=1, email="s@test.kg",
        )
        self.token = create_student_token(self.student)
        self.auth = CombinedJWTAuthentication()

    def _request(self):
        from rest_framework.test import APIRequestFactory
        request = APIRequestFactory().get("/")
        request.headers = {"Authorization": f"Bearer {self.token}"}
        return request

    def test_cache_miss_costs_exactly_one_query(self):
        with self.assertNumQueries(1):
            self.auth.authenticate(self._request())

    def test_cache_hit_makes_no_queries(self):
        """Ядро этапа 3: аутентификация не должна трогать базу при попадании."""
        self.auth.authenticate(self._request())  # прогрев

        with self.assertNumQueries(0):
            user, _ = self.auth.authenticate(self._request())

        self.assertEqual(str(user.id), str(self.student.id))
        self.assertEqual(str(user.university_id), str(self.uni.id))

    def test_miss_populates_cache(self):
        key = student_principal(self.student.id)
        self.assertIsNone(caches["default"].get(key))
        self.auth.authenticate(self._request())
        self.assertIsNotNone(caches["default"].get(key))

    def test_cached_payload_contains_no_pii(self):
        """В кэше только то, что нужно аутентификации (ТЗ п.18).

        Пароль ставится ДО выпуска токена: смена пароля у существующего
        студента отзывает его токены, и тест проверял бы не то.
        """
        self.student.phone_number = "+996700111222"
        self.student.password = make_password("secret-password")
        self.student.save()
        self.student.refresh_from_db()
        self.token = create_student_token(self.student)
        self.auth.authenticate(self._request())

        payload = caches["default"].get(student_principal(self.student.id))
        blob = str(payload)
        self.assertNotIn("+996700111222", blob)
        self.assertNotIn("secret-password", blob)
        self.assertNotIn(self.student.password, blob)
        self.assertNotIn("s@test.kg", blob)

    def test_lazy_student_is_not_loaded_for_auth(self):
        self.auth.authenticate(self._request())
        user, _ = self.auth.authenticate(self._request())
        self.assertIsNone(user._student, "полная модель не должна подгружаться при аутентификации")

        with self.assertNumQueries(1):
            _ = user.student  # обращение стоит ровно одного SELECT


class AuthCacheFormatTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        caches["default"].clear()
        self.uni = make_university()
        self.student = Student.objects.create(
            university=self.uni, student_id="S-1", full_name="Тест", course=1
        )
        self.token = create_student_token(self.student)

    def test_foreign_cache_payload_is_ignored(self):
        """Чужая или устаревшая запись не должна интерпретироваться как личность."""
        caches["default"].set(student_principal(self.student.id), {"v": 999, "id": "x"})
        res = self.client.get(
            "/api/v1/auth/student/me/", HTTP_AUTHORIZATION=f"Bearer {self.token}"
        )
        self.assertEqual(res.status_code, 200)

    def test_garbage_cache_payload_is_ignored(self):
        caches["default"].set(student_principal(self.student.id), "не словарь")
        res = self.client.get(
            "/api/v1/auth/student/me/", HTTP_AUTHORIZATION=f"Bearer {self.token}"
        )
        self.assertEqual(res.status_code, 200)

    def test_principal_roundtrip(self):
        principal = StudentPrincipal.from_model(self.student)
        self.assertEqual(StudentPrincipal.from_cache(principal.to_cache()), principal)


class RedisFailureTest(ContractTestCase):
    """ТЗ п.20: Redis не превращается в точку отказа для аутентификации."""

    def setUp(self):
        super().setUp()
        caches["default"].clear()
        self.uni = make_university()
        self.student = Student.objects.create(
            university=self.uni, student_id="S-1", full_name="Тест", course=1
        )
        self.token = create_student_token(self.student)

    def _me(self):
        return self.client.get(
            "/api/v1/auth/student/me/", HTTP_AUTHORIZATION=f"Bearer {self.token}"
        )

    def test_auth_works_when_cache_read_fails(self):
        import redis

        with mock.patch.object(
            caches["default"], "get", side_effect=redis.ConnectionError("Redis недоступен")
        ):
            self.assertEqual(self._me().status_code, 200)

    def test_auth_works_when_cache_write_fails(self):
        import redis

        with mock.patch.object(
            caches["default"], "set", side_effect=redis.ConnectionError("Redis недоступен")
        ):
            self.assertEqual(self._me().status_code, 200)
            self.assertEqual(self._me().status_code, 200)

    def test_voting_works_when_cache_is_down(self):
        import redis

        from apps.voting.models import Ballot, VoteRecord

        election = make_election(self.uni)
        candidate = make_candidate(election)
        with mock.patch.object(
            caches["default"], "get", side_effect=redis.ConnectionError("Redis недоступен")
        ):
            res = self.client.post(
                "/api/v1/voting/cast/",
                {"election_id": str(election.id), "candidate_id": str(candidate.id)},
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {self.token}",
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(VoteRecord.objects.count(), 1)
        self.assertEqual(Ballot.objects.count(), 1)


class AuthErrorMessageTest(ContractTestCase):
    """D-06: подробности исключения не уходят клиенту (ТЗ п.65)."""

    def test_invalid_token_message_is_generic(self):
        res = self.client.get(
            "/api/v1/auth/student/me/", HTTP_AUTHORIZATION="Bearer полная-ерунда"
        )
        self.assertIn(res.status_code, (401, 403))
        message = res.data["error"]["message"]
        for leak in ("Traceback", "jwt.", "Token is invalid", "algorithm", "Signature"):
            self.assertNotIn(leak, message, f"в ответ утекла деталь: {message}")

    def test_inactive_student_gets_clear_but_safe_message(self):
        uni = make_university()
        student = Student.objects.create(
            university=uni, student_id="S-1", full_name="Тест", course=1
        )
        token = create_student_token(student)
        student.is_active = False
        student.save(update_fields=["is_active"])

        res = self.client.get(
            "/api/v1/auth/student/me/", HTTP_AUTHORIZATION=f"Bearer {token}"
        )
        self.assertEqual(res.status_code, 403)


class BackwardCompatibilityTest(ContractTestCase):
    """ТЗ п.19: токены без claim auth_version обязаны дожить свой срок."""

    def setUp(self):
        super().setUp()
        caches["default"].clear()
        self.uni = make_university()
        self.student = Student.objects.create(
            university=self.uni, student_id="S-1", full_name="Тест", course=1
        )

    def _legacy_token(self):
        """Токен старого формата — ровно такой, какой выпускался до этапа 3."""
        import datetime

        import jwt
        from django.conf import settings
        from django.utils import timezone

        now = timezone.now()
        return jwt.encode(
            {
                "token_type": "student",
                "student_id": str(self.student.id),
                "university_id": str(self.uni.id),
                "student_code": self.student.student_id,
                "exp": int((now + datetime.timedelta(days=7)).timestamp()),
                "iat": int(now.timestamp()),
            },
            settings.SECRET_KEY,
            algorithm="HS256",
        )

    def _me(self, token):
        return self.client.get(
            "/api/v1/auth/student/me/", HTTP_AUTHORIZATION=f"Bearer {token}"
        )

    @override_settings(STUDENT_TOKEN_ALLOW_MISSING_AUTH_VERSION=True)
    def test_legacy_token_accepted_during_migration_period(self):
        self.assertEqual(self._me(self._legacy_token()).status_code, 200)

    @override_settings(STUDENT_TOKEN_ALLOW_MISSING_AUTH_VERSION=False)
    def test_legacy_token_rejected_after_migration_period(self):
        self.assertIn(self._me(self._legacy_token()).status_code, (401, 403))

    @override_settings(STUDENT_TOKEN_ALLOW_MISSING_AUTH_VERSION=True)
    def test_legacy_token_still_blocked_for_inactive_student(self):
        """Обратная совместимость не должна пропускать деактивированных."""
        token = self._legacy_token()
        self.student.is_active = False
        self.student.save(update_fields=["is_active"])
        self.assertEqual(self._me(token).status_code, 403)
