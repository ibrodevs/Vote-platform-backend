"""Стражи против возврата глобального row lock (ТЗ п.7).

Тесты из test_vote_concurrency.py прошли бы и со старым
`Election.objects.select_for_update()` — просто медленнее. Здесь проверяется
именно его отсутствие, а не только конечный результат.
"""
import inspect
import threading
from unittest import mock

from django.db import connection

from apps.voting import services as voting_services
from apps.voting.models import Ballot
from apps.voting.services import cast_secret_ballot

from tests.contract.factories import make_candidate, make_election, make_student, make_university

from .base import ConcurrencyTestCase


class NoRowLockInVotePathTest(ConcurrencyTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university()
        self.election = make_election(self.uni)
        self.candidate = make_candidate(self.election)

    def test_source_has_no_select_for_update(self):
        """Статический страж: дешёвый и срабатывает мгновенно при регрессии."""
        source = inspect.getsource(voting_services)
        self.assertNotIn(
            "select_for_update", source,
            "SELECT FOR UPDATE вернулся в путь голосования — это глобальная "
            "точка сериализации всех голосов одних выборов (ТЗ п.7)",
        )

    def test_two_votes_overlap_in_the_same_election(self):
        """Поведенческий страж: два голоса одних выборов пересекаются во времени.

        Поток A выполняет НАСТОЯЩИЙ голос и замирает внутри транзакции перед
        вставкой бюллетеня — то есть удерживает ровно те блокировки, которые
        берёт путь голосования. Поток B в это время голосует целиком.

        Со старым `Election.objects.select_for_update()` поток A держал бы на
        строке выборов FOR UPDATE, и B заблокировался бы: этот режим конфликтует
        даже с FOR KEY SHARE, который PostgreSQL берёт при вставке строки
        с внешним ключом. Тест проходит ровно потому, что путь голосования
        строку выборов больше не блокирует.
        """
        student_a = make_student(self.uni, student_id="S-A")
        student_b = make_student(self.uni, student_id="S-B")

        a_inside = threading.Event()
        let_a_finish = threading.Event()
        original_create = Ballot.objects.create
        pausing_thread = {}

        def create_with_pause(*args, **kwargs):
            if threading.current_thread().name == pausing_thread.get("name"):
                a_inside.set()
                let_a_finish.wait(20)
            return original_create(*args, **kwargs)

        failures = []

        def vote_a():
            pausing_thread["name"] = threading.current_thread().name
            try:
                cast_secret_ballot(student_a, str(self.election.id), str(self.candidate.id))
            except Exception as exc:
                failures.append(("A", exc))
            finally:
                connection.close()

        b_done = threading.Event()

        def vote_b():
            try:
                cast_secret_ballot(student_b, str(self.election.id), str(self.candidate.id))
                b_done.set()
            except Exception as exc:
                failures.append(("B", exc))
            finally:
                connection.close()

        with mock.patch.object(Ballot.objects, "create", create_with_pause):
            thread_a = threading.Thread(target=vote_a, name="voter-a")
            thread_a.start()
            self.assertTrue(a_inside.wait(10), "поток A не вошёл в транзакцию голосования")

            thread_b = threading.Thread(target=vote_b, name="voter-b")
            thread_b.start()
            b_completed = b_done.wait(10)

            let_a_finish.set()
            thread_a.join(30)
            thread_b.join(30)

        self.assertEqual(failures, [], f"голоса завершились ошибками: {failures}")
        self.assertTrue(
            b_completed,
            "второй голос заблокировался, пока первый был в транзакции — "
            "голоса одних выборов снова сериализуются (ТЗ п.7)",
        )
        self.assertVoteIntegrity(self.election, expected_votes=2)
