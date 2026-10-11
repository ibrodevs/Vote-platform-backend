"""Ограничение частоты запросов (ТЗ п.36).

Лимиты под тестами выключены глобально, поэтому здесь они включаются явно —
иначе сотни тестов, логинящихся с одного адреса, упирались бы в них.
"""
from django.core.cache import caches
from django.test import override_settings

from apps.core.throttling import (
    AuthAttemptThrottle,
    OtpVerifyThrottle,
    StudentActionThrottle,
    VoteThrottle,
)
from apps.students.models import Student
from apps.students.services_auth import create_student_token

from .base import ContractTestCase
from .factories import make_candidate, make_election, make_university

ENABLED = override_settings(RATE_LIMIT_ENABLED=True)


class ThrottleKeyTest(ContractTestCase):
    """Ключ определяет, кого именно ограничивает лимит."""

    def test_vote_throttle_keys_by_student_not_ip(self):
        """Главное требование ТЗ п.36.

        Ключ по IP заблокировал бы пять тысяч студентов за университетским
        NAT одновременно.
        """
        self.assertTrue(issubclass(VoteThrottle, StudentActionThrottle))
        uni = make_university()
        student = Student.objects.create(
            university=uni, student_id="S-1", full_name="Т", course=1
        )

        class FakeUser:
            is_student = True
            id = str(student.id)

        class FakeRequest:
            user = FakeUser()
            META = {"REMOTE_ADDR": "10.0.0.1"}

        key_a = VoteThrottle().get_cache_key(FakeRequest(), None)
        FakeRequest.META = {"REMOTE_ADDR": "10.0.0.2"}
        key_b = VoteThrottle().get_cache_key(FakeRequest(), None)
        self.assertEqual(key_a, key_b, "ключ не должен зависеть от IP")
        self.assertIn(str(student.id), key_a)

    def test_auth_throttle_keys_by_account_not_shared_nat(self):
        """Разные студенты за одним NAT получают разные pre-auth счётчики."""

        class FakeRequest:
            META = {"REMOTE_ADDR": "203.0.113.10"}

            def __init__(self, email):
                self.data = {"email": email, "password": "не читается"}

        throttle = AuthAttemptThrottle()
        key_a = throttle.get_cache_key(FakeRequest("a@uni.kg"), None)
        key_b = throttle.get_cache_key(FakeRequest("b@uni.kg"), None)
        self.assertNotEqual(key_a, key_b)
        self.assertNotIn("a@uni.kg", key_a)
        self.assertNotIn("b@uni.kg", key_b)

    def test_auth_throttle_same_account_is_same_across_ips(self):
        """Смена IP не должна обходить лимит перебора одного аккаунта."""

        class FakeRequest:
            data = {"email": "victim@uni.kg", "password": "x"}

            def __init__(self, ip):
                self.META = {"REMOTE_ADDR": ip}

        throttle = AuthAttemptThrottle()
        key_a = throttle.get_cache_key(FakeRequest("203.0.113.1"), None)
        key_b = throttle.get_cache_key(FakeRequest("198.51.100.2"), None)
        self.assertEqual(key_a, key_b)

    def test_otp_verify_keys_by_request_id(self):
        class FakeRequest:
            META = {"REMOTE_ADDR": "203.0.113.10"}

            def __init__(self, request_id):
                self.data = {"request_id": request_id, "code": "123456"}

        throttle = OtpVerifyThrottle()
        key_a = throttle.get_cache_key(
            FakeRequest("11111111-1111-1111-1111-111111111111"), None
        )
        key_b = throttle.get_cache_key(
            FakeRequest("22222222-2222-2222-2222-222222222222"), None
        )
        self.assertNotEqual(key_a, key_b)
        self.assertNotIn("11111111", key_a)

    def test_all_scopes_have_configured_rates(self):
        from django.conf import settings

        for throttle in (AuthAttemptThrottle, OtpVerifyThrottle,
                         StudentActionThrottle, VoteThrottle):
            with self.subTest(scope=throttle.scope):
                self.assertIn(throttle.scope, settings.RATE_LIMITS)


@ENABLED
class NatSharedIpTest(ContractTestCase):
    """Студенты за одним внешним IP не должны блокировать друг друга."""

    def setUp(self):
        super().setUp()
        caches["default"].clear()
        self.uni = make_university()
        self.election = make_election(self.uni)
        self.candidate = make_candidate(self.election)
        self.students = [
            Student.objects.create(university=self.uni, student_id=f"S-{i}",
                                   full_name=f"Студент {i}", course=1)
            for i in range(40)
        ]

    def test_many_students_from_one_ip_all_vote(self):
        """40 студентов с одного адреса — все голосуют.

        При лимите по IP (20/min) половина получила бы 429.
        """
        accepted = 0
        for student in self.students:
            headers = {"HTTP_AUTHORIZATION": f"Bearer {create_student_token(student)}",
                       "REMOTE_ADDR": "203.0.113.10"}
            with self.captureOnCommitCallbacks(execute=True):
                res = self.client.post(
                    "/api/v1/voting/cast/",
                    {"election_id": str(self.election.id),
                     "candidate_id": str(self.candidate.id)},
                    format="json", **headers,
                )
            self.assertNotEqual(res.status_code, 429,
                                f"студент {student.student_id} заблокирован лимитом по IP")
            if res.status_code == 200:
                accepted += 1
        self.assertEqual(accepted, 40)

    def test_single_student_hits_own_limit(self):
        """А вот один студент, долбящий endpoint, ограничивается."""
        student = self.students[0]
        headers = {"HTTP_AUTHORIZATION": f"Bearer {create_student_token(student)}",
                   "REMOTE_ADDR": "203.0.113.10"}
        statuses = []
        for _ in range(30):
            res = self.client.post(
                "/api/v1/voting/cast/",
                {"election_id": str(self.election.id),
                 "candidate_id": str(self.candidate.id)},
                format="json", **headers,
            )
            statuses.append(res.status_code)
        self.assertIn(429, statuses, "лимит по студенту не сработал")


@ENABLED
class AuthThrottleTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        caches["default"].clear()
        make_university(code="kstu")

    def test_repeated_login_attempts_are_throttled(self):
        """Перебор одного аккаунта останавливается независимо от NAT."""
        statuses = []
        for _ in range(30):
            res = self.client.post(
                "/api/v1/auth/student/login/",
                {"email": "victim@kstu.kg", "password": "попытка"},
                format="json", REMOTE_ADDR="198.51.100.7",
            )
            statuses.append(res.status_code)
        self.assertIn(429, statuses)

    def test_many_accounts_on_same_nat_do_not_share_auth_bucket(self):
        """Массовый вход в 12:00 не блокирует весь университет одним IP."""
        statuses = []
        for i in range(25):
            res = self.client.post(
                "/api/v1/auth/student/login/",
                {"email": f"student-{i}@kstu.kg", "password": "попытка"},
                format="json", REMOTE_ADDR="198.51.100.77",
            )
            statuses.append(res.status_code)
        self.assertNotIn(429, statuses)

    def test_admin_login_is_throttled(self):
        statuses = []
        for _ in range(30):
            res = self.client.post(
                "/api/v1/auth/admin/login/",
                {"email": "admin@test.kg", "password": "попытка"},
                format="json", REMOTE_ADDR="198.51.100.8",
            )
            statuses.append(res.status_code)
        self.assertIn(429, statuses)


class ThrottleDisableSwitchTest(ContractTestCase):
    """Лимиты обязаны отключаться для нагрузочного тестирования."""

    @override_settings(RATE_LIMIT_ENABLED=False)
    def test_disabled_switch_removes_all_limits(self):
        make_university(code="kstu")
        statuses = [
            self.client.post(
                "/api/v1/auth/student/login/",
                {"email": "a@kstu.kg", "password": "x"},
                format="json", REMOTE_ADDR="198.51.100.9",
            ).status_code
            for _ in range(40)
        ]
        self.assertNotIn(429, statuses, "выключатель лимитов не работает")


class LoginResponseUniformityTest(ContractTestCase):
    """ТЗ п.67: ответ не должен выдавать, существует ли аккаунт."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.hashers import make_password

        self.uni = make_university(code="kstu")
        Student.objects.create(
            university=self.uni, student_id="S-1", full_name="Т", course=1,
            email="known@kstu.kg", password=make_password("правильный-пароль"),
        )

    def test_unknown_email_and_wrong_password_are_indistinguishable(self):
        unknown = self.client.post(
            "/api/v1/auth/student/login/",
            {"email": "nobody@kstu.kg", "password": "любой"}, format="json",
        )
        wrong = self.client.post(
            "/api/v1/auth/student/login/",
            {"email": "known@kstu.kg", "password": "неверный"}, format="json",
        )
        self.assertEqual(unknown.status_code, wrong.status_code)
        self.assertEqual(unknown.data["error"]["code"], wrong.data["error"]["code"])
        self.assertEqual(unknown.data["error"]["message"], wrong.data["error"]["message"])

    def test_inactive_account_is_also_indistinguishable(self):
        from django.contrib.auth.hashers import make_password

        Student.objects.create(
            university=self.uni, student_id="S-2", full_name="Т", course=1,
            email="inactive@kstu.kg", password=make_password("пароль"),
            is_active=False,
        )
        inactive = self.client.post(
            "/api/v1/auth/student/login/",
            {"email": "inactive@kstu.kg", "password": "пароль"}, format="json",
        )
        unknown = self.client.post(
            "/api/v1/auth/student/login/",
            {"email": "nobody@kstu.kg", "password": "пароль"}, format="json",
        )
        self.assertEqual(inactive.data["error"]["code"], unknown.data["error"]["code"])


class AdminPathTest(ContractTestCase):
    def test_admin_path_is_configurable(self):
        from django.conf import settings

        self.assertTrue(settings.DJANGO_ADMIN_PATH)

    def test_default_admin_url_is_not_used(self):
        """Стандартный /admin/ находят автоматические сканеры за минуты."""
        self.assertEqual(self.client.get("/admin/").status_code, 404)
