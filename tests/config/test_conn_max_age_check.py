"""Проверка пары CONN_MAX_AGE + PgBouncer (этап 11).

Ошибиться в этой паре легко и дорого: Django не видит разницы между
PgBouncer и настоящим PostgreSQL. Обе ошибки симметричны и обе реальны,
поэтому проверяются обе.
"""
from django.test import SimpleTestCase, override_settings

from apps.core.system_checks import ALL_CHECKS, check_conn_max_age


class ConnMaxAgeCheckTest(SimpleTestCase):
    @override_settings(DB_CONN_MAX_AGE=0, DB_BEHIND_PGBOUNCER=False)
    def test_zero_without_pooler_fails(self):
        """Худшая из четырёх комбинаций: соединение на каждый запрос."""
        result = check_conn_max_age()
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 'conn_max_age_zero_without_pooler')
        # Подсказка обязана называть оба выхода, иначе она бесполезна
        # тому, кто читает её в CI в шесть утра.
        self.assertIn('DB_CONN_MAX_AGE=60', result.hint)
        self.assertIn('DB_BEHIND_PGBOUNCER=True', result.hint)

    @override_settings(DB_CONN_MAX_AGE=60, DB_BEHIND_PGBOUNCER=True)
    def test_persistent_connections_behind_pgbouncer_fail(self):
        """Обратная ошибка: persistent-соединения ломают transaction pooling."""
        result = check_conn_max_age()
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 'conn_max_age_with_pgbouncer')
        self.assertIn('DB_CONN_MAX_AGE=0', result.hint)

    @override_settings(DB_CONN_MAX_AGE=60, DB_BEHIND_PGBOUNCER=False)
    def test_direct_connection_with_reuse_passes(self):
        result = check_conn_max_age()
        self.assertTrue(result.ok, result.message)

    @override_settings(DB_CONN_MAX_AGE=0, DB_BEHIND_PGBOUNCER=True)
    def test_pgbouncer_with_zero_passes(self):
        result = check_conn_max_age()
        self.assertTrue(result.ok, result.message)

    def test_check_is_registered(self):
        """Проверка, которую забыли включить в набор, не проверяет ничего."""
        self.assertIn(check_conn_max_age, ALL_CHECKS)
