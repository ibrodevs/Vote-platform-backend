"""Проверки production-конфигурации (ТЗ п.102, 103, дефект D-10)."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from apps.core import system_checks


class IndividualCheckTest(SimpleTestCase):
    @override_settings(DEBUG=True)
    def test_debug_enabled_fails(self):
        self.assertFalse(system_checks.check_debug().ok)

    @override_settings(DEBUG=False)
    def test_debug_disabled_passes(self):
        self.assertTrue(system_checks.check_debug().ok)

    @override_settings(SECRET_KEY=system_checks.LEAKED_SECRET_KEY)
    def test_leaked_secret_key_fails(self):
        result = system_checks.check_secret_key()
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 'secret_key_leaked')

    @override_settings(SECRET_KEY='short')
    def test_short_secret_key_fails(self):
        """D-10: PyJWT предупреждает о ключах короче 32 байт для HMAC SHA256."""
        result = system_checks.check_secret_key()
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 'secret_key_too_short')

    @override_settings(SECRET_KEY='x' * 31)
    def test_secret_key_just_below_threshold_fails(self):
        self.assertFalse(system_checks.check_secret_key().ok)

    @override_settings(SECRET_KEY='x' * 32)
    def test_secret_key_at_threshold_passes(self):
        self.assertTrue(system_checks.check_secret_key().ok)

    @override_settings(ALLOWED_HOSTS=['*'])
    def test_wildcard_hosts_fails(self):
        result = system_checks.check_allowed_hosts()
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 'allowed_hosts_wildcard')

    @override_settings(ALLOWED_HOSTS=[])
    def test_empty_hosts_fails(self):
        self.assertFalse(system_checks.check_allowed_hosts().ok)

    @override_settings(ALLOWED_HOSTS=['api.example.kg'])
    def test_explicit_hosts_passes(self):
        self.assertTrue(system_checks.check_allowed_hosts().ok)

    @override_settings(CORS_ALLOW_ALL_ORIGINS=True)
    def test_open_cors_fails(self):
        self.assertFalse(system_checks.check_cors().ok)

    @override_settings(CORS_ALLOW_ALL_ORIGINS=False, CORS_ALLOWED_ORIGINS=[])
    def test_empty_cors_fails(self):
        self.assertFalse(system_checks.check_cors().ok)

    @override_settings(CORS_ALLOW_ALL_ORIGINS=False,
                       CORS_ALLOWED_ORIGINS=['https://vote.example.kg'])
    def test_explicit_cors_passes(self):
        self.assertTrue(system_checks.check_cors().ok)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_eager_celery_fails(self):
        self.assertFalse(system_checks.check_celery().ok)

    @override_settings(MOCK_SMS=True)
    def test_demo_otp_fails(self):
        result = system_checks.check_demo_otp()
        self.assertFalse(result.ok)
        self.assertIn('под любым', result.hint)

    @override_settings(X_FRAME_OPTIONS='ALLOWALL')
    def test_allowall_frames_fails(self):
        self.assertFalse(system_checks.check_clickjacking().ok)

    @override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=True, SECURE_SSL_REDIRECT=True, DEPLOYMENT_STAGE='production', IS_BOOTSTRAP=False)
    def test_insecure_session_cookie_fails(self):
        self.assertFalse(system_checks.check_ssl_settings().ok)

    @override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=False, SECURE_SSL_REDIRECT=True, DEPLOYMENT_STAGE='production', IS_BOOTSTRAP=False)
    def test_insecure_csrf_cookie_fails(self):
        self.assertFalse(system_checks.check_ssl_settings().ok)

    @override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True, SECURE_SSL_REDIRECT=False, DEPLOYMENT_STAGE='production', IS_BOOTSTRAP=False)
    def test_missing_ssl_redirect_fails_in_production(self):
        result = system_checks.check_ssl_settings()
        self.assertFalse(result.ok)
        self.assertIn('SECURE_SSL_REDIRECT', result.message)

    @override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True, SECURE_SSL_REDIRECT=True, DEPLOYMENT_STAGE='production', IS_BOOTSTRAP=False)
    def test_production_mode_passes_when_all_secure(self):
        result = system_checks.check_ssl_settings()
        self.assertTrue(result.ok)
        self.assertEqual(result.code, 'secure_cookies')

    @override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, SECURE_SSL_REDIRECT=False, DEPLOYMENT_STAGE='bootstrap', IS_BOOTSTRAP=True)
    def test_bootstrap_mode_allows_insecure_cookies_and_no_ssl_redirect(self):
        result = system_checks.check_ssl_settings()
        self.assertTrue(result.ok)
        self.assertEqual(result.code, 'secure_cookies_bootstrap')

    def test_every_failure_has_a_hint(self):
        """Сообщение без подсказки заставляет гадать, что чинить."""
        with override_settings(DEBUG=True, SECRET_KEY='short', ALLOWED_HOSTS=['*'],
                               CORS_ALLOW_ALL_ORIGINS=True, CELERY_TASK_ALWAYS_EAGER=True,
                               MOCK_SMS=True, X_FRAME_OPTIONS='ALLOWALL',
                               SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
                               SECURE_SSL_REDIRECT=False, DEPLOYMENT_STAGE='production',
                               IS_BOOTSTRAP=False):
            for result in system_checks.run_all(skip={'check_migrations'}):
                if not result.ok:
                    with self.subTest(check=result.code):
                        self.assertTrue(result.hint, f'{result.code} без подсказки')


class ProductionCheckCommandTest(SimpleTestCase):
    databases = {'default'}

    @override_settings(DEBUG=True)
    def test_command_fails_on_problems(self):
        with self.assertRaises(CommandError):
            call_command('production_check', stdout=StringIO(), stderr=StringIO())

    @override_settings(DEBUG=True)
    def test_warn_only_does_not_raise(self):
        out = StringIO()
        call_command('production_check', '--warn-only', stdout=out, stderr=StringIO())
        self.assertIn('Проблем', out.getvalue())

    @override_settings(DEBUG=True)
    def test_output_lists_each_check(self):
        out = StringIO()
        call_command('production_check', '--warn-only', stdout=out, stderr=StringIO())
        self.assertIn('DEBUG=True', out.getvalue())

    def test_skip_argument_works(self):
        out = StringIO()
        call_command('production_check', '--warn-only',
                     '--skip', 'check_migrations', 'check_debug',
                     stdout=out, stderr=StringIO())
        self.assertNotIn('DEBUG', out.getvalue())

    @override_settings(
        DEBUG=False,
        SECRET_KEY='valid-long-secret-key-for-test-at-least-32-chars-long',
        ALLOWED_HOSTS=['195.201.12.34'],
        CORS_ALLOW_ALL_ORIGINS=False,
        CORS_ALLOWED_ORIGINS=['http://195.201.12.34:3000'],
        CELERY_TASK_ALWAYS_EAGER=False,
        MOCK_SMS=False,
        X_FRAME_OPTIONS='DENY',
        SESSION_COOKIE_SECURE=False,
        CSRF_COOKIE_SECURE=False,
        SECURE_SSL_REDIRECT=False,
        DEPLOYMENT_STAGE='bootstrap',
        IS_BOOTSTRAP=True,
        REDIS_URL='redis://localhost:6379/1',
        DB_BEHIND_PGBOUNCER=True,
        DB_CONN_MAX_AGE=0,
        CACHES={'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache'}},
        AWS_STORAGE_BUCKET_NAME='vote-media',
    )
    def test_bootstrap_mode_production_check_passes(self):
        out = StringIO()
        call_command('production_check', '--skip', 'check_migrations', 'check_database_engine', stdout=out, stderr=StringIO())
        self.assertIn('Все 12 проверок пройдены', out.getvalue())

    @override_settings(
        DEBUG=False,
        SECRET_KEY='valid-long-secret-key-for-test-at-least-32-chars-long',
        ALLOWED_HOSTS=['api.example.kg'],
        CORS_ALLOW_ALL_ORIGINS=False,
        CORS_ALLOWED_ORIGINS=['https://vote.example.kg'],
        CELERY_TASK_ALWAYS_EAGER=False,
        MOCK_SMS=False,
        X_FRAME_OPTIONS='DENY',
        SESSION_COOKIE_SECURE=False,
        CSRF_COOKIE_SECURE=False,
        SECURE_SSL_REDIRECT=False,
        DEPLOYMENT_STAGE='production',
        IS_BOOTSTRAP=False,
        REDIS_URL='redis://localhost:6379/1',
        DB_BEHIND_PGBOUNCER=True,
        DB_CONN_MAX_AGE=0,
        CACHES={'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache'}},
        AWS_STORAGE_BUCKET_NAME='vote-media',
    )
    def test_production_mode_fails_if_ssl_missing(self):
        with self.assertRaises(CommandError):
            call_command('production_check', '--skip', 'check_migrations', stdout=StringIO(), stderr=StringIO())
