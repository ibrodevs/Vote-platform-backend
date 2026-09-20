"""Health-чеки (ТЗ п.43)."""
from unittest import mock

from django.core.cache import caches
from django.db import connection
from django.test.utils import CaptureQueriesContext

from .base import ContractTestCase


class LivenessTest(ContractTestCase):
    def test_liveness_returns_200(self):
        res = self.client.get("/health/live")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "alive")

    def test_liveness_makes_no_database_queries(self):
        """Иначе проблема с базой вызовет перезапуск всех инстансов разом."""
        with CaptureQueriesContext(connection) as ctx:
            self.client.get("/health/live")
        self.assertEqual(
            [q for q in ctx.captured_queries if "SELECT 1" in q["sql"]], [],
            "liveness не должен ходить в базу",
        )


class ReadinessTest(ContractTestCase):
    def test_readiness_ok(self):
        res = self.client.get("/health/ready")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["checks"]["database"], "ok")

    def test_redis_down_does_not_make_unready(self):
        """ТЗ п.43: предусмотрен fallback в PostgreSQL."""
        import redis

        with mock.patch.object(
            caches["default"], "set", side_effect=redis.ConnectionError("нет Redis")
        ):
            res = self.client.get("/health/ready")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["checks"]["cache"], "degraded")

    def test_database_down_makes_unready(self):
        with mock.patch("apps.core.health.connection") as fake:
            fake.cursor.side_effect = RuntimeError("база недоступна")
            res = self.client.get("/health/ready")
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["status"], "not_ready")

    def test_legacy_health_endpoint_still_works(self):
        res = self.client.get("/api/health/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "healthy", "service": "dobush-backend"})
