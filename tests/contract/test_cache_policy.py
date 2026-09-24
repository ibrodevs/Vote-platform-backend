"""Политика кэширования задана явно (ТЗ п.113)."""
import uuid

from django.test import SimpleTestCase

from apps.core import cache_keys
from apps.core.cache_policy import CachePolicy


class CachePolicyTest(SimpleTestCase):
    def test_all_ttls_are_positive_integers(self):
        for name in dir(CachePolicy):
            if name.startswith("_"):
                continue
            value = getattr(CachePolicy, name)
            with self.subTest(policy=name):
                self.assertIsInstance(value, int)
                self.assertGreater(value, 0, f"{name} должен быть задан явно")

    def test_turnout_ttl_is_seconds_not_minutes(self):
        """ТЗ п.29 допускает задержку в несколько секунд, но не минут."""
        self.assertLessEqual(CachePolicy.ELECTION_TURNOUT, 30)

    def test_positive_vote_status_outlives_any_election(self):
        """Факт участия необратим — кэш не должен истечь посреди выборов."""
        self.assertGreaterEqual(CachePolicy.VOTE_STATUS_POSITIVE, 24 * 60 * 60)

    def test_final_results_cached_long(self):
        self.assertGreaterEqual(CachePolicy.ELECTION_FINAL_RESULTS, 60 * 60)


class CacheKeySeparationTest(SimpleTestCase):
    def test_turnout_and_results_keys_are_distinct(self):
        """ТЗ п.51: общий ключ сделал бы явку каналом утечки результатов."""
        election_id = uuid.uuid4()
        self.assertNotEqual(
            cache_keys.election_turnout(election_id),
            cache_keys.election_results(election_id),
        )

    def test_all_election_keys_share_prefix(self):
        election_id = uuid.uuid4()
        prefix = cache_keys.election_namespace_prefix(election_id)
        for key in (
            cache_keys.election_turnout(election_id),
            cache_keys.election_results(election_id),
            cache_keys.election_public(election_id),
        ):
            self.assertTrue(key.startswith(prefix), key)

    def test_vote_status_key_has_no_candidate(self):
        """Ключ статуса не должен содержать кандидата (ТЗ п.4)."""
        key = cache_keys.student_vote_status(uuid.uuid4(), uuid.uuid4())
        self.assertNotIn("candidate", key.lower())
