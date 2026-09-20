"""Тесты мгновенного отзыва студенческих токенов (ТЗ п.19, дефект D-04).

Токен живёт 7 дней. Без механизма отзыва отчисленный или заблокированный
студент продолжал бы голосовать всю неделю.
"""
from django.contrib.auth.hashers import make_password
from django.test import TestCase

from apps.students.models import Student
from apps.students.services_auth import (
    create_student_token,
    invalidate_principal,
    revoke_student_tokens,
)

from .base import ContractTestCase
from .factories import make_university


class AuthVersionModelTest(TestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university()
        self.student = Student.objects.create(
            university=self.uni, student_id="S-1", full_name="Тест", course=1
        )

    def test_auth_version_starts_at_one(self):
        """Старт с 1, а не с 0: так отличается «версия есть» от «claim отсутствует»."""
        self.assertEqual(self.student.auth_version, 1)

    def test_revoke_increments_version(self):
        new_version = revoke_student_tokens(self.student)
        self.assertEqual(new_version, 2)
        self.student.refresh_from_db()
        self.assertEqual(self.student.auth_version, 2)

    def test_two_revokes_give_two_increments(self):
        """F-выражение вместо чтения и записи: иначе параллельные отзывы
        дали бы одну версию вместо двух."""
        revoke_student_tokens(self.student)
        revoke_student_tokens(self.student)
        self.student.refresh_from_db()
        self.assertEqual(self.student.auth_version, 3)

    def test_deactivation_bumps_version(self):
        self.student.is_active = False
        self.student.save(update_fields=["is_active"])
        self.student.refresh_from_db()
        self.assertEqual(self.student.auth_version, 2)

    def test_reactivation_does_not_bump(self):
        """Повторная активация не должна воскрешать старые токены —
        но и новую версию плодить незачем."""
        self.student.is_active = False
        self.student.save(update_fields=["is_active"])
        version_after_deactivation = Student.objects.get(pk=self.student.pk).auth_version

        self.student.refresh_from_db()
        self.student.is_active = True
        self.student.save(update_fields=["is_active"])
        self.student.refresh_from_db()
        self.assertEqual(self.student.auth_version, version_after_deactivation)

    def test_password_change_bumps_version(self):
        self.student.password = make_password("new-password-123")
        self.student.save(update_fields=["password"])
        self.student.refresh_from_db()
        self.assertEqual(self.student.auth_version, 2)

    def test_unrelated_update_does_not_bump(self):
        self.student.full_name = "Новое Имя"
        self.student.save(update_fields=["full_name"])
        self.student.refresh_from_db()
        self.assertEqual(self.student.auth_version, 1)


class TokenRevocationApiTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university()
        self.student = Student.objects.create(
            university=self.uni, student_id="S-1", full_name="Тест", course=1,
            password=make_password("studentpass123"), email="s@test.kg",
        )
        self.token = create_student_token(self.student)

    def _me(self, token=None):
        return self.client.get(
            "/api/v1/auth/student/me/",
            HTTP_AUTHORIZATION=f"Bearer {token or self.token}",
        )

    def test_valid_token_works(self):
        self.assertEqual(self._me().status_code, 200)

    def test_deactivating_student_revokes_tokens(self):
        """D-04: раньше деактивированный студент продолжал работать."""
        self.assertEqual(self._me().status_code, 200)
        self.student.is_active = False
        self.student.save(update_fields=["is_active"])
        self.assertEqual(self._me().status_code, 403)

    def test_password_change_revokes_tokens(self):
        self.assertEqual(self._me().status_code, 200)
        self.student.password = make_password("brand-new-password")
        self.student.save(update_fields=["password"])
        self.assertEqual(self._me().status_code, 403)

    def test_explicit_revoke_invalidates_token(self):
        self.assertEqual(self._me().status_code, 200)
        revoke_student_tokens(self.student)
        self.assertEqual(self._me().status_code, 403)

    def test_new_token_after_revoke_works(self):
        revoke_student_tokens(self.student)
        self.student.refresh_from_db()
        fresh = create_student_token(self.student)
        self.assertEqual(self._me(token=fresh).status_code, 200)
        self.assertEqual(self._me().status_code, 403, "старый токен обязан остаться мёртвым")

    def test_revoke_works_even_if_cache_is_stale(self):
        """Отзыв не должен зависеть от успешности инвалидации кэша.

        Версия сверяется с принципалом, но принципал перечитывается из БД,
        если версия в кэше не сходится с токеном.
        """
        self._me()  # прогрев кэша
        revoke_student_tokens(self.student)
        self.assertEqual(self._me().status_code, 403)

    def test_deactivated_student_cannot_vote(self):
        from apps.voting.models import VoteRecord

        from .factories import make_candidate, make_election

        election = make_election(self.uni)
        candidate = make_candidate(election)
        self.student.is_active = False
        self.student.save(update_fields=["is_active"])

        res = self.client.post(
            "/api/v1/voting/cast/",
            {"election_id": str(election.id), "candidate_id": str(candidate.id)},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(VoteRecord.objects.count(), 0)
