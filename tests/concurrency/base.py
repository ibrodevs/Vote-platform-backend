"""Инфраструктура concurrency-тестов.

Все тесты здесь идут ТОЛЬКО на PostgreSQL. На SQLite нет advisory locks,
другая модель конкуррентности и другие блокировки — зелёный прогон там
ничего не доказывает (ТЗ п.107).
"""
import concurrent.futures
import threading

from django.db import connection
from django.test import TransactionTestCase

# PostgreSQL по умолчанию держит max_connections=100. Каждый поток открывает
# собственное соединение, поэтому параллелизм ограничен сознательно.
MAX_WORKERS = 24

SKIP_REASON = (
    "concurrency-тесты имеют смысл только на PostgreSQL: на SQLite нет "
    "advisory locks и другая модель блокировок. "
    "Запуск: DJANGO_SETTINGS_MODULE=config.settings_test python manage.py test tests.concurrency"
)


class ConcurrencyTestCase(TransactionTestCase):
    """База для тестов параллельного голосования."""

    def setUp(self):
        super().setUp()
        if connection.vendor != "postgresql":
            self.skipTest(SKIP_REASON)

    def run_concurrently(self, fn, count, max_workers=MAX_WORKERS, barrier=True):
        """Выполняет fn(i) в count потоках и возвращает (успехи, исключения).

        Каждый поток ОБЯЗАН закрыть своё соединение: иначе исчерпается
        max_connections, а тестовую базу нельзя будет удалить в teardown.
        Эта ошибка уже ловилась на этапе 1.

        barrier=True синхронизирует старт всех потоков, чтобы они действительно
        пересекались во времени, а не выполнялись по очереди.
        """
        results, errors = [], []
        lock = threading.Lock()
        gate = threading.Barrier(min(count, max_workers)) if barrier else None

        def worker(index):
            try:
                if gate is not None:
                    try:
                        gate.wait(timeout=30)
                    except threading.BrokenBarrierError:
                        pass
                value = fn(index)
                with lock:
                    results.append(value)
            except Exception as exc:
                with lock:
                    errors.append(exc)
            finally:
                connection.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(worker, i) for i in range(count)]
            concurrent.futures.wait(futures, timeout=180)

        return results, errors

    def assertVoteIntegrity(self, election, expected_votes):
        """Главный acceptance-критерий: записей об участии и бюллетеней поровну."""
        from apps.voting.models import Ballot, VoteRecord

        records = VoteRecord.objects.filter(election=election).count()
        ballots = Ballot.objects.filter(election=election).count()
        self.assertEqual(records, expected_votes, "неверное число записей об участии")
        self.assertEqual(ballots, expected_votes, "неверное число бюллетеней")
        self.assertEqual(records, ballots, "частично записанный голос: VoteRecord != Ballot")

    def deadlock_count(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT deadlocks FROM pg_stat_database WHERE datname = current_database()"
            )
            return cursor.fetchone()[0]
