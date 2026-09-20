"""Тесты advisory-локов (ТЗ п.8).

Shared-лок берут голоса — они обязаны идти параллельно.
Exclusive-лок берут операции смены состояния выборов — они обязаны дождаться
уже начатых голосов и не пустить новые в критическую секцию.
"""
import threading
import time
import uuid

from django.db import connection, transaction
from django.test import TransactionTestCase, SimpleTestCase, skipUnlessDBFeature

from apps.core.db_locks import (
    advisory_lock_key,
    election_state_lock,
    election_vote_lock,
    supports_advisory_locks,
)

IS_POSTGRES = connection.vendor == "postgresql"
SKIP_REASON = "advisory locks есть только в PostgreSQL; зелёный прогон на SQLite ничего не доказывает"


class AdvisoryLockKeyTest(SimpleTestCase):
    def test_key_is_stable_across_calls(self):
        value = uuid.uuid4()
        self.assertEqual(
            advisory_lock_key("election", value),
            advisory_lock_key("election", value),
        )

    def test_key_is_stable_for_str_and_uuid(self):
        value = uuid.uuid4()
        self.assertEqual(
            advisory_lock_key("election", value),
            advisory_lock_key("election", str(value)),
        )

    def test_key_fits_signed_bigint(self):
        for _ in range(100):
            key = advisory_lock_key("election", uuid.uuid4())
            self.assertGreaterEqual(key, -(2 ** 63))
            self.assertLess(key, 2 ** 63)

    def test_different_values_give_different_keys(self):
        keys = {advisory_lock_key("election", uuid.uuid4()) for _ in range(500)}
        self.assertEqual(len(keys), 500)

    def test_namespace_separates_keys(self):
        value = uuid.uuid4()
        self.assertNotEqual(
            advisory_lock_key("election", value),
            advisory_lock_key("student", value),
        )


class AdvisoryLockTransactionGuardTest(TransactionTestCase):
    """Вне транзакции pg_advisory_xact_lock освобождается немедленно.

    Молчаливый no-op здесь опаснее падения: код выглядел бы защищённым,
    не будучи защищённым. Поэтому вызов вне atomic() — ошибка.
    """

    def test_vote_lock_requires_transaction(self):
        with self.assertRaises(RuntimeError):
            election_vote_lock(uuid.uuid4())

    def test_state_lock_requires_transaction(self):
        with self.assertRaises(RuntimeError):
            election_state_lock(uuid.uuid4())

    def test_locks_work_inside_transaction(self):
        with transaction.atomic():
            election_vote_lock(uuid.uuid4())
            election_state_lock(uuid.uuid4())


class AdvisoryLockSemanticsTest(TransactionTestCase):
    """Проверка самой сути: shared параллелен, exclusive — барьер."""

    def setUp(self):
        super().setUp()
        if not IS_POSTGRES:
            self.skipTest(SKIP_REASON)

    def _hold_lock(self, lock_fn, election_id, acquired, release, result_box, timeout=5):
        def worker():
            try:
                with transaction.atomic():
                    lock_fn(election_id)
                    acquired.set()
                    release.wait(timeout)
                result_box.append("ok")
            except Exception as exc:  # pragma: no cover
                result_box.append(exc)
            finally:
                connection.close()

        thread = threading.Thread(target=worker)
        thread.start()
        return thread

    def test_two_shared_locks_coexist(self):
        election_id = uuid.uuid4()
        acquired_a, release_a, box_a = threading.Event(), threading.Event(), []
        thread_a = self._hold_lock(election_vote_lock, election_id, acquired_a, release_a, box_a)
        self.assertTrue(acquired_a.wait(5), "первый shared-лок не взят")

        # Второй shared-лок обязан взяться, пока первый удерживается
        acquired_b, release_b, box_b = threading.Event(), threading.Event(), []
        thread_b = self._hold_lock(election_vote_lock, election_id, acquired_b, release_b, box_b)
        got_b = acquired_b.wait(5)

        release_a.set()
        release_b.set()
        thread_a.join(10)
        thread_b.join(10)

        self.assertTrue(got_b, "два shared-лока на одни выборы должны сосуществовать")

    def test_exclusive_blocks_shared(self):
        election_id = uuid.uuid4()
        acquired, release, box = threading.Event(), threading.Event(), []
        holder = self._hold_lock(election_state_lock, election_id, acquired, release, box, timeout=10)
        self.assertTrue(acquired.wait(5), "exclusive-лок не взят")

        got_shared = threading.Event()

        def try_shared():
            try:
                with transaction.atomic():
                    election_vote_lock(election_id)
                    got_shared.set()
            finally:
                connection.close()

        waiter = threading.Thread(target=try_shared)
        waiter.start()

        # Пока exclusive удерживается, shared взяться не должен
        self.assertFalse(
            got_shared.wait(1.5),
            "shared-лок взялся при удерживаемом exclusive — барьер finish не работает",
        )

        release.set()
        holder.join(10)
        self.assertTrue(got_shared.wait(5), "shared-лок не взялся после освобождения exclusive")
        waiter.join(10)

    def test_different_elections_do_not_block(self):
        acquired, release, box = threading.Event(), threading.Event(), []
        holder = self._hold_lock(election_state_lock, uuid.uuid4(), acquired, release, box)
        self.assertTrue(acquired.wait(5))

        got_other = threading.Event()

        def other_election():
            try:
                with transaction.atomic():
                    election_vote_lock(uuid.uuid4())
                    got_other.set()
            finally:
                connection.close()

        thread = threading.Thread(target=other_election)
        thread.start()
        ok = got_other.wait(5)
        release.set()
        holder.join(10)
        thread.join(10)
        self.assertTrue(ok, "лок одних выборов не должен блокировать другие")


class AdvisoryLockBackendTest(TransactionTestCase):
    def test_supports_advisory_locks_matches_vendor(self):
        self.assertEqual(supports_advisory_locks(), connection.vendor == "postgresql")

    def test_noop_on_non_postgres(self):
        """На SQLite локи деградируют в no-op, иначе локальная разработка встанет."""
        if IS_POSTGRES:
            self.skipTest("проверяется только на не-PostgreSQL")
        with transaction.atomic():
            election_vote_lock(uuid.uuid4())
            election_state_lock(uuid.uuid4())
