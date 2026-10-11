"""Тесты конфигурации БД (ТЗ п.12, 102).

Проверяют production PostgreSQL и безопасную комбинацию persistent Django
connections + PgBouncer transaction pooling.
"""
import importlib
import os
import unittest
from unittest import mock

from django.core.exceptions import ImproperlyConfigured

DB_ENV_KEYS = (
    "DJANGO_ENV", "DB_ENGINE", "DB_NAME", "DB_USER",
    "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_CONN_MAX_AGE",
    "DB_BEHIND_PGBOUNCER", "DB_DISABLE_SERVER_SIDE_CURSORS",
)

PRODUCTION_PREREQS = {
    "DJANGO_SECRET_KEY": "x" * 64,
    "DJANGO_ALLOWED_HOSTS": "api.example.kg",
    "DJANGO_CORS_ALLOWED_ORIGINS": "https://vote.example.kg",
    "DJANGO_DEBUG": "False",
}


class DatabaseConfigTest(unittest.TestCase):
    def _reload_with(self, **env):
        cleared = {k: None for k in DB_ENV_KEYS}
        cleared.update(PRODUCTION_PREREQS)
        cleared.update(env)
        patch = {k: v for k, v in cleared.items() if v is not None}
        removed = [k for k, v in cleared.items() if v is None]
        with mock.patch.dict(os.environ, patch, clear=False):
            for key in removed:
                os.environ.pop(key, None)
            import config.settings as settings_module
            return importlib.reload(settings_module)

    def tearDown(self):
        for key in DB_ENV_KEYS:
            os.environ.pop(key, None)
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
        s = self._reload_with()
        self.assertFalse(s.IS_PRODUCTION)
        self.assertEqual(s.DJANGO_ENV, "development")
        self.assertEqual(s.DATABASES["default"]["ENGINE"], "django.db.backends.sqlite3")

    def test_development_still_allows_mysql(self):
        s = self._reload_with(DB_ENGINE="mysql")
        self.assertEqual(s.DATABASES["default"]["ENGINE"], "django.db.backends.mysql")

    def test_conn_max_age_defaults_to_zero(self):
        s = self._reload_with(DB_ENGINE="postgresql")
        self.assertEqual(s.DATABASES["default"]["CONN_MAX_AGE"], 0)

    def test_conn_max_age_from_env(self):
        s = self._reload_with(DB_ENGINE="postgresql", DB_CONN_MAX_AGE="60")
        self.assertEqual(s.DATABASES["default"]["CONN_MAX_AGE"], 60)

    def test_pgbouncer_disables_server_side_cursors_by_default(self):
        s = self._reload_with(
            DB_ENGINE="postgresql",
            DB_BEHIND_PGBOUNCER="True",
            DB_CONN_MAX_AGE="60",
        )
        self.assertTrue(s.DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"])

    def test_direct_postgres_keeps_server_side_cursors_by_default(self):
        s = self._reload_with(
            DB_ENGINE="postgresql",
            DB_BEHIND_PGBOUNCER="False",
        )
        self.assertFalse(s.DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"])

    def test_cursor_setting_can_be_explicitly_overridden(self):
        s = self._reload_with(
            DB_ENGINE="postgresql",
            DB_BEHIND_PGBOUNCER="True",
            DB_DISABLE_SERVER_SIDE_CURSORS="False",
        )
        self.assertFalse(s.DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"])

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
