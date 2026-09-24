"""Подсчёт итогов голосования (ТЗ п.27, 28, 29, 51).

ПОЧЕМУ ОТДЕЛЬНЫЙ МОДУЛЬ
-----------------------
Результаты считались в двух местах — во вьюхе `results/` и во вьюхе
`results/export/` — двумя копиями кода. Копии уже начали расходиться:
`turnout/` берёт число проголосовавших из VoteRecord, а `results/` — из Ballot.
Эти числа обязаны совпадать (иначе нарушен инвариант атомарности), но
считались они независимо, и рассинхронизация прошла бы незамеченной.

ПОЧЕМУ ОДИН GROUP BY
--------------------
Было: `for candidate: Ballot.objects.filter(...).count()` — 1+N запросов.
На выборах с 25 кандидатами это 25 отдельных COUNT'ов вместо одного.
Стало: один `values('candidate_id').annotate(Count('id'))`.

ТАЙНА ГОЛОСОВАНИЯ
-----------------
Агрегация идёт ТОЛЬКО по Ballot и ТОЛЬКО по candidate_id. Ни один запрос
здесь не соединяет Student с Candidate и не имеет права этого делать.
"""
from typing import Any

from django.db.models import Count

from apps.candidates.models import Candidate
from apps.core.cache import safe_get, safe_set
from apps.core.cache_keys import election_results as results_key
from apps.core.cache_keys import election_turnout as turnout_key
from apps.core.cache_policy import CachePolicy
from apps.students.models import Student
from apps.voting.models import Ballot, VoteRecord

from .models import Election


def results_are_visible(election: Election) -> bool:
    """Правило видимости результатов из ТЗ п.51, в одном месте.

    Пока выборы не завершены и флаг не выставлен, результаты не отдаются
    никому — ни в JSON, ни в Excel. Оптимизация и кэширование не должны
    случайно открыть их раньше времени.
    """
    return (
        election.status == Election.Status.FINISHED
        or election.results_visible_to_admin_before_finish
    )


def eligible_voters_count(election: Election) -> int:
    """Число избирателей: активные студенты университета.

    Точный подсчёт из PostgreSQL. Запрос идёт по Index Only Scan
    (`student_uni_active_idx`, 0.88 мс на 200 000 студентов, этап 5),
    поэтому отдельного кэша не требует. Источником истины остаётся база.
    """
    return Student.objects.filter(university_id=election.university_id, is_active=True).count()


def election_turnout(election: Election) -> dict[str, Any]:
    """Явка. Для идущих выборов кэшируется на секунды (ТЗ п.29).

    ТЗ п.30 запрещает счётчик-строку вроде `election.vote_count += 1`:
    он вернул бы сериализацию всех голосов через одну строку — ровно то,
    что убирал этап 2. Поэтому короткий кэш поверх обычного COUNT.

    Для завершённых выборов кэш не нужен: их явка уже не меняется,
    а точность важнее (ТЗ п.29 — «финальный turnout вычисляется точно»).
    """
    is_live = election.status == Election.Status.ACTIVE

    if is_live:
        cached = safe_get(turnout_key(election.id))
        if cached is not None:
            return cached

    total_eligible = eligible_voters_count(election)
    total_voted = VoteRecord.objects.filter(election_id=election.id).count()
    payload = {
        "total_eligible": total_eligible,
        "total_voted": total_voted,
        "turnout_percent": (
            round((total_voted / total_eligible * 100), 2) if total_eligible else 0.0
        ),
    }

    if is_live:
        safe_set(turnout_key(election.id), payload, timeout=CachePolicy.ELECTION_TURNOUT)

    return payload


def election_results(election: Election) -> dict[str, Any]:
    """Итоги выборов: явка и голоса по кандидатам.

    Три запроса независимо от числа кандидатов:
      1. кандидаты выборов,
      2. один GROUP BY по бюллетеням,
      3. число избирателей.

    КЭШИРУЮТСЯ ТОЛЬКО ЗАВЕРШЁННЫЕ ВЫБОРЫ (ТЗ п.28).
    Итоги идущих не кэшируются вовсе: запись пережила бы смену состояния
    и могла бы отдать цифры, которые уже нельзя показывать (ТЗ п.51).
    """
    is_final = election.status == Election.Status.FINISHED

    if is_final:
        cached = safe_get(results_key(election.id))
        if cached is not None:
            return cached

    candidates = list(
        Candidate.objects.filter(election_id=election.id).order_by('order', 'created_at')
    )

    # Один агрегат вместо COUNT на каждого кандидата
    tally = {
        row['candidate_id']: row['votes']
        for row in Ballot.objects.filter(election_id=election.id)
        .values('candidate_id')
        .annotate(votes=Count('id'))
    }

    total_voted = sum(tally.values())
    total_eligible = eligible_voters_count(election)
    turnout_percent = round((total_voted / total_eligible * 100), 2) if total_eligible else 0.0

    rows = []
    for candidate in candidates:
        votes = tally.get(candidate.id, 0)
        rows.append({
            "candidate_id": str(candidate.id),
            "full_name": candidate.full_name,
            "photo": candidate.photo.url if candidate.photo else None,
            "photo_url": candidate.photo_url,
            "faculty": candidate.faculty,
            "course": candidate.course,
            "position": candidate.position,
            "votes": votes,
            "percent": round((votes / total_voted * 100), 2) if total_voted else 0.0,
        })

    # Лидер первым — часть контракта, зафиксированная тестом
    rows.sort(key=lambda row: row["votes"], reverse=True)

    payload = {
        "total_eligible": total_eligible,
        "total_voted": total_voted,
        "turnout_percent": turnout_percent,
        "candidates": rows,
    }

    if is_final:
        safe_set(results_key(election.id), payload, timeout=CachePolicy.ELECTION_FINAL_RESULTS)

    return payload
