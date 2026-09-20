"""Тесты конфигурации БД (ТЗ п.12, 102).

Проверяют, что production физически не может стартовать на SQLite или MySQL,
и что поведение по умолчанию (без новых переменных) не изменилось —
иначе сломается уже работающий деплой.
"""
import importlib
import os
import unittest
from unittest import mock

from django.core.exceptions import ImproperlyConfigured

DB_ENV_KEYS = (
    "DJANGO_ENV", "DB_ENGINE", "DB_NAME", "DB_USER",
    "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_CONN_MAX_AGE",
)


class DatabaseConfigTest(unittest.TestCase):
    """Каждый кейс перезагружает config.settings с нужным окружением.

    Настройки, уже загруженные для текущего прогона, восстанавливаются
    в tearDown — иначе повторный импорт оставит после себя чужую конфигурацию.
    """

    def _reload_with(self, **env):
        cleared = {k: None for k in DB_ENV_KEYS}
        cleared.update(env)
        patch = {k: v for k, v in cleared.items() if v is not None}
        removed = [k for k, v in cleared.items() if v is None]
        with mock.patch.dict(os.environ, patch, clear=False):
            for key in removed:
                os.environ.pop(key, None)
            import config.settings as settings_module
            return importlib.reload(settings_module)

    def tearDown(self):
        import config.settings as settings_module
        importlib.reload(settings_module)

    def test_production_rejects_sqlite(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            self._reload_with(DJANGO_ENV="production", DB_ENGINE="sqlite")
        self.assertIn("postgresql", str(ctx.exception))

    def test_production_rejects_mysql(self):
        with self.assertRaises(ImproperlyConfigured):
            self._reload_with(DJANGO_ENV="production", DB_ENGINE="mysql")

    def test_production_accepts_postgresql(self):
        s = self._reload_with(DJANGO_ENV="production", DB_ENGINE="postgresql")
        self.assertTrue(s.IS_PRODUCTION)
        self.assertEqual(s.DATABASES["default"]["ENGINE"], "django.db.backends.postgresql")

    def test_production_defaults_to_postgresql(self):
        s = self._reload_with(DJANGO_ENV="production")
        self.assertEqual(s.DATABASES["default"]["ENGINE"], "django.db.backends.postgresql")

    def test_development_defaults_to_sqlite(self):
        """Поведение по умолчанию не изменилось — живой деплой не ломается."""
        s = self._reload_with()
        self.assertFalse(s.IS_PRODUCTION)
        self.assertEqual(s.DJANGO_ENV, "development")
        self.assertEqual(s.DATABASES["default"]["ENGINE"], "django.db.backends.sqlite3")

    def test_development_still_allows_mysql(self):
        s = self._reload_with(DB_ENGINE="mysql")
        self.assertEqual(s.DATABASES["default"]["ENGINE"], "django.db.backends.mysql")

    def test_conn_max_age_defaults_to_zero(self):
        """0 выбран осознанно: persistent-соединения вредны за PgBouncer (ТЗ п.13)."""
        s = self._reload_with(DB_ENGINE="postgresql")
        self.assertEqual(s.DATABASES["default"]["CONN_MAX_AGE"], 0)

    def test_conn_max_age_from_env(self):
        s = self._reload_with(DB_ENGINE="postgresql", DB_CONN_MAX_AGE="60")
        self.assertEqual(s.DATABASES["default"]["CONN_MAX_AGE"], 60)

    def test_postgres_connection_params_from_env(self):
        s = self._reload_with(
            DB_ENGINE="postgresql", DB_NAME="votes", DB_USER="voter",
            DB_PASSWORD="secret", DB_HOST="db.internal", DB_PORT="6432",
        )
        cfg = s.DATABASES["default"]
        self.assertEqual(cfg["NAME"], "votes")
        self.assertEqual(cfg["USER"], "voter")
        self.assertEqual(cfg["HOST"], "db.internal")
        self.assertEqual(cfg["PORT"], "6432")

    def test_django_env_is_case_and_space_tolerant(self):
        s = self._reload_with(DJANGO_ENV="  Production  ", DB_ENGINE="postgresql")
        self.assertTrue(s.IS_PRODUCTION)
