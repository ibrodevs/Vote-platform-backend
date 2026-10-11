"""Явная инвалидация кэша (ТЗ п.24).

TTL — вторая линия. Изменения моделей по возможности удаляют зависимые ключи
сразу, чтобы администратор видел результат без ожидания TTL.
"""
import logging

from apps.core.cache import safe_delete
from apps.core.cache_keys import (
    active_elections_catalog,
    election_public,
    election_results,
    election_student_detail,
    election_turnout,
    student_principal,
    university,
)

logger = logging.getLogger(__name__)


def _election_university_id(election_id):
    """Редкий admin/invalidation path: один SELECT допустим ради точного сброса."""
    try:
        from apps.elections.models import Election
        return (
            Election.objects.filter(id=election_id)
            .values_list('university_id', flat=True)
            .first()
        )
    except Exception:
        logger.warning(
            "cache_invalidation_election_university_lookup_failed election_id=%s",
            election_id,
            exc_info=True,
        )
        return None


def invalidate_election(election_id, university_id=None) -> None:
    """Сбрасывает публичные/агрегированные ключи выборов.

    Активный каталог ключуется по университету, потому что один и тот же payload
    разделяют все студенты этого университета. Если caller уже знает university_id,
    он может передать его и избежать дополнительного SELECT.
    """
    if university_id is None:
        university_id = _election_university_id(election_id)

    for key in (
        election_public(election_id),
        election_student_detail(election_id),
        election_turnout(election_id),
        election_results(election_id),
    ):
        safe_delete(key)

    if university_id is not None:
        safe_delete(active_elections_catalog(university_id))

    logger.debug("cache_invalidated_election election_id=%s", election_id)


def invalidate_candidate(candidate) -> None:
    """Изменение кандидата меняет и общий активный каталог его университета."""
    invalidate_election(candidate.election_id, candidate.university_id)


def invalidate_university(university_id) -> None:
    safe_delete(university(university_id))
    safe_delete(active_elections_catalog(university_id))


def invalidate_student(student_id) -> None:
    """Личность студента. Дублирует signal для путей без save()."""
    safe_delete(student_principal(student_id))
