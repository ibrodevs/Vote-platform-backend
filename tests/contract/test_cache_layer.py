"""Тесты слоя кэша (ТЗ п.20, 23).

Главное требование: ни один вызов кэша не должен уметь уронить запрос.
Redis — ускоритель, а не источник истины и не точка отказа.
"""
import uuid
from unittest import mock

from django.core.cache import caches
from django.test import SimpleTestCase

from apps.core import cache_keys
from apps.core.cache import cache_available, safe_delete, safe_get, safe_set


class CacheKeyTest(SimpleTestCase):
    def test_namespace_is_versioned(self):
        self.assertEqual(cache_keys.NAMESPACE, "voteplatform:v1")

    def test_student_principal_key_format(self):
        student_id = uuid.uuid4()
        key = cache_keys.student_principal(student_id)
        self.assertTrue(key.startswith("voteplatform:v1:student:"))
        self.assertTrue(key.endswith(":principal"))
        self.assertIn(str(student_id), key)

    def test_keys_are_distinct_per_student(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        self.assertNotEqual(cache_keys.student_principal(a), cache_keys.student_principal(b))

    def test_key_is_stable_for_str_and_uuid(self):
        value = uuid.uuid4()
        self.assertEqual(
            cache_keys.student_principal(value),
            cache_keys.student_principal(str(value)),
        )


class SafeCacheTest(SimpleTestCase):
    def setUp(self):
        super().setUp()
        caches["default"].clear()

    def test_roundtrip(self):
        self.assertTrue(safe_set("k", {"a": 1}, timeout=60))
        self.assertEqual(safe_get("k"), {"a": 1})
        self.assertTrue(safe_delete("k"))
        self.assertIsNone(safe_get("k"))

    def test_safe_get_returns_default_when_cache_raises(self):
        with mock.patch.object(caches["default"], "get", side_effect=RuntimeError("boom")):
            self.assertIsNone(safe_get("k"))
            self.assertEqual(safe_get("k", default="fallback"), "fallback")

    def test_safe_set_returns_false_on_error(self):
        with mock.patch.object(caches["default"], "set", side_effect=RuntimeError("boom")):
            self.assertFalse(safe_set("k", 1, timeout=60))

    def test_safe_delete_never_raises(self):
        with mock.patch.object(caches["default"], "delete", side_effect=RuntimeError("boom")):
            self.assertFalse(safe_delete("k"))

    def test_connection_error_is_swallowed(self):
        """Недоступный Redis не должен превращаться в ошибку запроса."""
        import redis

        with mock.patch.object(
            caches["default"], "get", side_effect=redis.ConnectionError("Redis недоступен")
        ):
            self.assertIsNone(safe_get("k"))

    def test_cache_available_reflects_state(self):
        self.assertTrue(cache_available())
        with mock.patch.object(caches["default"], "set", side_effect=RuntimeError("boom")):
            self.assertFalse(cache_available())
