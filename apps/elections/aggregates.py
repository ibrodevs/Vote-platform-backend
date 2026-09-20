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
from django.db.models import Count

from apps.candidates.models import Candidate
from apps.students.models import Student
from apps.voting.models import Ballot

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

    ТЗ п.29 запрещает бездумный COUNT(*) на каждый запрос при большой таблице.
    Кэширование этого числа — этап 6; здесь сознательно оставлен точный
    подсчёт, потому что источником истины обязан остаться PostgreSQL.
    """
    return Student.objects.filter(university_id=election.university_id, is_active=True).count()


def election_results(election: Election) -> dict:
    """Итоги выборов: явка и голоса по кандидатам.

    Три запроса независимо от числа кандидатов:
      1. кандидаты выборов,
      2. один GROUP BY по бюллетеням,
      3. число избирателей.
    """
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

    return {
        "total_eligible": total_eligible,
        "total_voted": total_voted,
        "turnout_percent": turnout_percent,
        "candidates": rows,
    }
