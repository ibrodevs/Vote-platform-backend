"""Операции смены состояния выборов.

Вынесено из views, чтобы блокировки и бизнес-правила не размазывались
по слою представления (ТЗ п.104), и чтобы одна и та же логика работала
одинаково из API, админки и management-команд.

СИНХРОНИЗАЦИЯ С ГОЛОСОВАНИЕМ (ТЗ п.8)
-------------------------------------
Каждая операция берёт EXCLUSIVE advisory-лок по election_id, тогда как
голоса берут SHARED по тому же ключу. Отсюда порядок:

  1. finish ждёт, пока завершатся уже начатые транзакции голосования;
  2. новые голоса не входят в критическую секцию, пока finish держит лок;
  3. finish меняет статус и коммитит;
  4. ожидавшие голоса читают уже FINISHED и отклоняются.

Никаких частично записанных голосов при этом не возникает: голос либо
успевает целиком до барьера, либо целиком откатывается.

ПЕРЕХОДЫ СОСТОЯНИЙ
------------------
Терминальные статусы (finished, cancelled) покидать нельзя — иначе
завершённые выборы переоткрываются и голосование идёт поверх готовых
результатов. Повторный вызов той же операции идемпотентен: админ, дважды
нажавший кнопку, ошибки не получает.
"""
from django.db import transaction

from apps.core.cache_invalidation import invalidate_election
from apps.core.db_locks import election_state_lock

from .models import Election

TERMINAL_STATUSES = frozenset({Election.Status.FINISHED, Election.Status.CANCELLED})


class ElectionStateError(Exception):
    def __init__(self, message, code="invalid_status_transition"):
        super().__init__(message)
        self.message = message
        self.code = code


def _reject_transition(current, target):
    raise ElectionStateError(
        f"Невозможно перевести выборы из состояния «{current}» в «{target}». "
        "Завершённые и отменённые выборы нельзя запустить заново.",
        code="invalid_status_transition",
    )


def start_election(election: Election) -> Election:
    """draft/scheduled -> active. Повтор для active — no-op."""
    with transaction.atomic():
        election_state_lock(election.id)
        election.refresh_from_db()

        if election.status == Election.Status.ACTIVE:
            return election
        if election.status in TERMINAL_STATUSES:
            _reject_transition(election.get_status_display(), "активные")

        if not election.candidates.exists():
            raise ElectionStateError(
                "Нельзя запустить выборы без кандидатов", code="no_candidates"
            )

        election.status = Election.Status.ACTIVE
        election.save(update_fields=["status"])
        # Смена состояния меняет и публичные данные, и видимость результатов
        transaction.on_commit(lambda: invalidate_election(election.id))
        return election


def finish_election(election: Election) -> Election:
    """Любой нетерминальный статус -> finished. Повтор для finished — no-op.

    Именно здесь стоит барьер для параллельных голосов.
    """
    with transaction.atomic():
        election_state_lock(election.id)
        election.refresh_from_db()

        if election.status == Election.Status.FINISHED:
            return election
        if election.status == Election.Status.CANCELLED:
            _reject_transition(election.get_status_display(), "завершённые")

        election.status = Election.Status.FINISHED
        election.save(update_fields=["status"])
        # Смена состояния меняет и публичные данные, и видимость результатов
        transaction.on_commit(lambda: invalidate_election(election.id))
        return election


def cancel_election(election: Election) -> Election:
    """Любой незавершённый статус -> cancelled. Повтор для cancelled — no-op."""
    with transaction.atomic():
        election_state_lock(election.id)
        election.refresh_from_db()

        if election.status == Election.Status.CANCELLED:
            return election
        if election.status == Election.Status.FINISHED:
            _reject_transition(election.get_status_display(), "отменённые")

        election.status = Election.Status.CANCELLED
        election.save(update_fields=["status"])
        # Смена состояния меняет и публичные данные, и видимость результатов
        transaction.on_commit(lambda: invalidate_election(election.id))
        return election


def delete_election(election: Election) -> None:
    """Удаление запрещено во время активного голосования.

    Удаление каскадом снесло бы VoteRecord и Ballot — то есть поданные голоса.
    """
    with transaction.atomic():
        election_state_lock(election.id)
        election.refresh_from_db()

        if election.status == Election.Status.ACTIVE:
            raise ElectionStateError(
                "Невозможно удалить активные выборы. Сначала отмените или завершите их.",
                code="active_election",
            )
        election_id = election.id
        election.delete()
        transaction.on_commit(lambda: invalidate_election(election_id))
