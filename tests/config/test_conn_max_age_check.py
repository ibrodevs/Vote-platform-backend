"""Проверка пары CONN_MAX_AGE + PgBouncer transaction pooling."""
from django.test import SimpleTestCase, override_settings

from apps.core.system_checks import ALL_CHECKS, check_conn_max_age


SAFE_PGBOUNCER_DATABASES = {
    'default': {'DISABLE_SERVER_SIDE_CURSORS': True},
}
UNSAFE_PGBOUNCER_DATABASES = {
    'default': {'DISABLE_SERVER_SIDE_CURSORS': False},
}


class ConnMaxAgeCheckTest(SimpleTestCase):
    @override_settings(DB_CONN_MAX_AGE=0, DB_BEHIND_PGBOUNCER=False)
    def test_zero_without_pooler_fails(self):
        result = check_conn_max_age()
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 'conn_max_age_zero_without_pooler')
        self.assertIn('DB_CONN_MAX_AGE=60', result.hint)

    @override_settings(
        DB_CONN_MAX_AGE=60,
        DB_BEHIND_PGBOUNCER=True,
        DATABASES=SAFE_PGBOUNCER_DATABASES,
    )
    def test_persistent_connections_behind_pgbouncer_pass_when_cursors_disabled(self):
        """Django->PgBouncer reuse безопасен при client-side cursors."""
        result = check_conn_max_age()
        self.assertTrue(result.ok, result.message)
        self.assertIn('CONN_MAX_AGE=60', result.message)

    @override_settings(
        DB_CONN_MAX_AGE=60,
        DB_BEHIND_PGBOUNCER=True,
        DATABASES=UNSAFE_PGBOUNCER_DATABASES,
    )
    def test_server_side_cursors_behind_transaction_pool_fail(self):
        result = check_conn_max_age()
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 'server_side_cursors_with_pgbouncer')
        self.assertIn('DB_DISABLE_SERVER_SIDE_CURSORS=True', result.hint)

    @override_settings(DB_CONN_MAX_AGE=60, DB_BEHIND_PGBOUNCER=False)
    def test_direct_connection_with_reuse_passes(self):
        result = check_conn_max_age()
        self.assertTrue(result.ok, result.message)

    @override_settings(
        DB_CONN_MAX_AGE=0,
        DB_BEHIND_PGBOUNCER=True,
        DATABASES=SAFE_PGBOUNCER_DATABASES,
    )
    def test_pgbouncer_with_zero_still_passes(self):
        result = check_conn_max_age()
        self.assertTrue(result.ok, result.message)

    def test_check_is_registered(self):
        self.assertIn(check_conn_max_age, ALL_CHECKS)
