"""Ключи кэша (ТЗ п.23).

Единственное место в проекте, где формируются имена ключей. Неймспейс
версионирован: при несовместимом изменении формата достаточно поднять версию.
"""
import uuid as uuid_module

NAMESPACE = "voteplatform:v1"


def _normalize(value) -> str:
    """UUID и его строковое представление обязаны давать один ключ."""
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
    """Положительный факт участия; ключ принципиально не содержит кандидата."""
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


def active_elections_catalog(university_id) -> str:
    """Общая для всех студентов сериализованная часть активных выборов.

    Персональный `has_voted` сюда никогда не попадает. Это позволяет тысячам
    студентов одного университета не сериализовать один и тот же список
    кандидатов и не читать те же Election/Candidate строки из PostgreSQL.
    """
    return f"{NAMESPACE}:university:{_normalize(university_id)}:active-elections"


def election_turnout(election_id) -> str:
    """Явка идущих выборов."""
    return f"{NAMESPACE}:election:{_normalize(election_id)}:turnout"


def election_results(election_id) -> str:
    """Итоги ЗАВЕРШЁННЫХ выборов. Незавершённые не кэшируются."""
    return f"{NAMESPACE}:election:{_normalize(election_id)}:results"


def election_namespace_prefix(election_id) -> str:
    """Префикс всех ключей выборов — для инвалидации скопом."""
    return f"{NAMESPACE}:election:{_normalize(election_id)}:"
