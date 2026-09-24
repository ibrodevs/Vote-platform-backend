"""Явная инвалидация кэша (ТЗ п.24).

ТЗ прямо требует: «Не рассчитывать исключительно на TTL. TTL является
дополнительной защитой, но основная invalidation должна происходить явно».

Причина в том, что TTL — это окно, в течение которого администратор видит
свои же изменения ненаступившими. Пять минут на вопрос «почему кандидат
не появился» — это пять минут, за которые он успеет нажать кнопку ещё трижды.
"""
import logging

from apps.core.cache import safe_delete
from apps.core.cache_keys import (
    election_public,
    election_results,
    election_turnout,
    student_principal,
    university,
)

logger = logging.getLogger(__name__)


def invalidate_election(election_id) -> None:
    """Сбрасывает все ключи выборов.

    Вызывается и при смене состояния: переход в FINISHED меняет видимость
    результатов, поэтому старая запись стала бы неверной (ТЗ п.51).
    """
    for key in (
        election_public(election_id),
        election_turnout(election_id),
        election_results(election_id),
    ):
        safe_delete(key)
    logger.debug("cache_invalidated_election election_id=%s", election_id)


def invalidate_candidate(candidate) -> None:
    """Изменение кандидата меняет публичные данные его выборов и их итоги."""
    invalidate_election(candidate.election_id)


def invalidate_university(university_id) -> None:
    safe_delete(university(university_id))


def invalidate_student(student_id) -> None:
    """Личность студента. Дублирует сигнал из apps/students/signals.py —
    нужен для путей, которые save() не вызывают."""
    safe_delete(student_principal(student_id))
