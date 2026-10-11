"""Бюджет SQL round trips на горячем пути записи (ТЗ п.83, 84; этап 11).

Зачем это отдельный тест, а не число в отчёте.

Абсолютное время на этой машине ничего не говорит о боевом сервере:
генератор нагрузки делит с приложением и базой одни 8 ядер. А вот число
обращений к базе на одну операцию от железа не зависит вовсе — оно
одинаково на ноутбуке и на проде. Причём на проде каждое обращение стоит
дороже: между приложением и PostgreSQL появляется сеть, которой на
loopback нет. Поэтому именно это число является допустимым основанием
для оптимизации, а «медленно выглядит» — нет.

Тест фиксирует бюджет как контракт: если кто-то добавит в путь голосования
лишний SELECT, набор станет красным и заставит это обосновать.

Только PostgreSQL: на SQLite нет advisory locks, и число запросов там
другое — зелёный прогон на SQLite ничего не доказывал бы.
"""
from django.db import connection
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from apps.voting.models import Ballot, VoteRecord
from apps.voting.services import AlreadyVotedError, cast_secret_ballot

from tests.contract.factories import make_candidate, make_election, make_student, make_university

SKIP_REASON = (
    "бюджет round trips имеет смысл только на PostgreSQL: на SQLite нет "
    "advisory locks и путь голосования короче"
)


class VoteQueryBudgetTest(TransactionTestCase):
    """Сколько раз голосование обращается к базе."""

    # Состав успешного голосования после election-day оптимизации:
    # каждая строка один round trip до сервера PostgreSQL:
    #
    #   1. BEGIN
    #   2. SELECT pg_advisory_xact_lock_shared(...) — SHARED-лок выборов
    #   3. SELECT candidate JOIN election           — кандидат + состояние
    #                                                  выборов одним запросом
    #   4. SAVEPOINT                                — нужен для IntegrityError
    #   5. INSERT INTO voting_voterecord ...        — факт участия
    #   6. RELEASE SAVEPOINT
    #   7. INSERT INTO voting_ballot ...            — сам бюллетень
    #   8. COMMIT
    #
    # Раньше Election и Candidate читались двумя отдельными SELECT и бюджет
    # был 9. Для 1000+ vote/s один убранный round trip означает тысячи
    # сетевых обращений к PostgreSQL в секунду, не меняя гарантий голосования.
    EXPECTED_QUERIES = 8

    def setUp(self):
        super().setUp()
        if connection.vendor != "postgresql":
            self.skipTest(SKIP_REASON)
        self.uni = make_university()
        self.student = make_student(self.uni, student_id="S-BUDGET")
        self.election = make_election(self.uni)
        self.candidate = make_candidate(self.election)

    def test_successful_vote_query_budget(self):
        with CaptureQueriesContext(connection) as ctx:
            cast_secret_ballot(self.student, str(self.election.id), str(self.candidate.id))

        statements = [q["sql"] for q in ctx.captured_queries]
        self.assertEqual(
            len(statements),
            self.EXPECTED_QUERIES,
            "изменился бюджет обращений к базе на одно голосование.\n"
            "Это не обязательно ошибка, но обязательно требует обоснования.\n"
            "Фактические запросы:\n  " + "\n  ".join(statements),
        )
        self.assertEqual(VoteRecord.objects.filter(election=self.election).count(), 1)
        self.assertEqual(Ballot.objects.filter(election=self.election).count(), 1)

    def test_duplicate_vote_query_budget(self):
        """Повторная попытка не должна быть дороже успешной."""
        cast_secret_ballot(self.student, str(self.election.id), str(self.candidate.id))

        with CaptureQueriesContext(connection) as ctx:
            with self.assertRaises(AlreadyVotedError):
                cast_secret_ballot(self.student, str(self.election.id), str(self.candidate.id))

        statements = [q["sql"] for q in ctx.captured_queries]
        self.assertLessEqual(
            len(statements),
            self.EXPECTED_QUERIES,
            "отказ дубликату стал дороже успешного голоса — это открывает "
            "дешёвый способ нагружать базу повторными запросами.\n"
            "Фактические запросы:\n  " + "\n  ".join(statements),
        )
        self.assertEqual(VoteRecord.objects.filter(election=self.election).count(), 1)
        self.assertEqual(Ballot.objects.filter(election=self.election).count(), 1)
