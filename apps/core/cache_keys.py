"""Ключи кэша (ТЗ п.23).

Единственное место в проекте, где формируются имена ключей. Разрозненные
ad-hoc строки по коду приводят к тому, что инвалидация промахивается мимо
записи, которую собиралась удалить.

Неймспейс версионирован: при несовместимом изменении формата значений
достаточно поднять версию, и старые записи перестают читаться, а не
интерпретируются неверно.
"""
import uuid as uuid_module

NAMESPACE = "voteplatform:v1"


def _normalize(value) -> str:
    """UUID и его строковое представление обязаны давать один ключ.

    Иначе запись, сделанная по объекту UUID, не находилась бы по строке
    из JWT, и кэш молча не работал бы.
    """
    if isinstance(value, uuid_module.UUID):
        return str(value)
    try:
        return str(uuid_module.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return str(value)


def student_principal(student_id) -> str:
    """Личность студента для аутентификации."""
    return f"{NAMESPACE}:student:{_normalize(student_id)}:principal"


def student_vote_status(student_id, election_id) -> str:
    """Факт участия студента в выборах.

    Заготовка для этапа 6. Ключ НЕ содержит кандидата: он и не должен —
    иначе кэш восстанавливал бы выбор студента (ТЗ п.4).
    """
    return (
        f"{NAMESPACE}:student:{_normalize(student_id)}"
        f":vote:{_normalize(election_id)}"
    )


def election_public(election_id) -> str:
    """Публичные данные выборов."""
    return f"{NAMESPACE}:election:{_normalize(election_id)}:public"


def university(university_id) -> str:
    """Данные университета."""
    return f"{NAMESPACE}:university:{_normalize(university_id)}"


def election_turnout(election_id) -> str:
    """Явка идущих выборов.

    Ключ отдельный от результатов намеренно (ТЗ п.51): явка показывается
    всегда, а результаты — только после завершения. Общий ключ сделал бы
    кэш явки каналом утечки результатов.
    """
    return f"{NAMESPACE}:election:{_normalize(election_id)}:turnout"


def election_results(election_id) -> str:
    """Итоги ЗАВЕРШЁННЫХ выборов. Незавершённые не кэшируются."""
    return f"{NAMESPACE}:election:{_normalize(election_id)}:results"


def election_namespace_prefix(election_id) -> str:
    """Префикс всех ключей выборов — для инвалидации скопом."""
    return f"{NAMESPACE}:election:{_normalize(election_id)}:"
