"""Сервис тайного голосования.

==============================================================================
ИНВАРИАНТЫ — НЕ НАРУШАТЬ (ТЗ п.3, 5, 6, 11, 106)
==============================================================================
DO NOT add student relation to Ballot
DO NOT add candidate relation to VoteRecord
DO NOT replace database uniqueness with a cache check
DO NOT move the core vote commit to an asynchronous queue
DO NOT reintroduce SELECT FOR UPDATE on Election in the vote path
DO NOT log student_id and candidate_id together, anywhere, ever

Оптимизация, нарушившая хотя бы один из этих пунктов, откатывается,
даже если она повышает пропускную способность.
==============================================================================

ПОЧЕМУ ЗДЕСЬ НЕТ SELECT FOR UPDATE
----------------------------------
Раньше каждый голос брал row lock на строку Election. Это делало её единственной
точкой сериализации: все голоса одних выборов выстраивались в очередь за одной
блокировкой (ТЗ п.7). Теперь голос берёт SHARED advisory-лок — такие локи
держатся одновременно, поэтому голоса идут параллельно, но операция смены
состояния выборов (EXCLUSIVE-лок) по-прежнему получает честный барьер.

ПОЧЕМУ НЕТ ПРОВЕРКИ exists() ПЕРЕД ВСТАВКОЙ
--------------------------------------------
Проверка "уже голосовал?" отдельным запросом проигрывает гонке: два запроса
успевают прочитать exists()=False до того, как любой из них вставит строку.
Здесь сразу выполняется INSERT, а защиту даёт UNIQUE-констрейнт базы — он
в гонке не проигрывает никогда (ТЗ п.6). Заодно это на один SQL-запрос меньше
на каждом голосе.
"""
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.candidates.models import Candidate
from apps.core.cache import safe_set
from apps.core.cache_keys import student_vote_status
from apps.core.cache_policy import CachePolicy
from apps.core.db_locks import election_vote_lock
from apps.elections.models import Election

from .models import Ballot, VoteRecord

logger = logging.getLogger('apps.voting')

UNIQUE_VOTE_CONSTRAINT = 'uniq_voterecord_election_student'


def _is_duplicate_vote(exc: IntegrityError) -> bool:
    """Отличает нарушение UNIQUE(election, student) от прочих IntegrityError.

    Слепо считать любой IntegrityError дублем нельзя: нарушение FK или CHECK
    тогда превратилось бы в "вы уже проголосовали", и настоящая ошибка была бы
    скрыта от разработчика и от пользователя.

    PostgreSQL называет констрейнт в diag.constraint_name — это самый надёжный
    признак. SQLite имён констрейнтов в сообщении не приводит вовсе и пишет
    список колонок, поэтому для локальной разработки нужен второй признак.
    """
    cause = getattr(exc, '__cause__', None)
    constraint_name = getattr(getattr(cause, 'diag', None), 'constraint_name', None)
    if constraint_name:
        return constraint_name == UNIQUE_VOTE_CONSTRAINT

    message = str(exc)
    if UNIQUE_VOTE_CONSTRAINT in message:
        return True
    # SQLite: "UNIQUE constraint failed: voting_voterecord.election_id, voting_voterecord.student_id"
    return (
        'UNIQUE constraint failed' in message
        and 'election_id' in message
        and 'student_id' in message
    )


class VotingError(Exception):
    def __init__(self, message, code="voting_error"):
        super().__init__(message)
        self.message = message
        self.code = code


class AlreadyVotedError(VotingError):
    def __init__(self):
        super().__init__("Вы уже проголосовали в этих выборах", code="already_voted")


class ElectionNotActiveError(VotingError):
    def __init__(self):
        super().__init__("Выборы не активны или время голосования не наступило / истекло", code="election_not_active")


class IneligibleStudentError(VotingError):
    def __init__(self):
        super().__init__("Вы не являетесь студентом университета, проводящего данные выборы", code="ineligible_student")


class InvalidCandidateError(VotingError):
    def __init__(self):
        super().__init__("Указанный кандидат не участвует в данных выборах", code="invalid_candidate")


def cast_secret_ballot(student, election_id: str, candidate_id: str) -> bool:
    """Принимает один тайный голос.

    `student` — любой объект с `.id` и `.university_id`: и модель Student,
    и StudentPrincipal из кэша аутентификации. Горячий путь передаёт принципал,
    чтобы не делать лишний SELECT полной модели (ТЗ п.18).

    Возвращает True только после фактического COMMIT обеих строк.
    При любой ошибке транзакция полностью откатывается: состояний
    "есть VoteRecord без Ballot" или "есть Ballot без VoteRecord"
    после коммита не существует (ТЗ п.5).

    Внутри транзакции нет сетевых вызовов, Redis, файловых операций
    и тяжёлой сериализации — транзакция обязана быть короткой (ТЗ п.89).
    """
    now = timezone.now()

    with transaction.atomic():
        # SHARED-лок: голоса одних выборов держат его одновременно и друг друга
        # не ждут. Ждёт только тот, кто меняет состояние выборов (ТЗ п.8).
        election_vote_lock(election_id)

        try:
            election = Election.objects.get(id=election_id)
        except Election.DoesNotExist:
            raise VotingError("Выборы не найдены", code="election_not_found")

        if election.status != Election.Status.ACTIVE:
            raise ElectionNotActiveError()
        if not (election.starts_at <= now <= election.ends_at):
            raise ElectionNotActiveError()

        # Университет берётся ТОЛЬКО из аутентифицированной личности,
        # никогда из тела запроса (ТЗ п.53).
        #
        # Сравнение через str: у модели Student это UUID, у StudentPrincipal
        # из кэша — строка (иначе он не сериализуется). Без нормализации
        # сравнение было бы всегда ложным, и ни один голос не проходил бы.
        if str(election.university_id) != str(student.university_id):
            raise IneligibleStudentError()

        if not Candidate.objects.filter(id=candidate_id, election_id=election.id).exists():
            raise InvalidCandidateError()

        # Savepoint обязателен. Без него IntegrityError оставляет транзакцию
        # PostgreSQL в broken state, и следующий же SQL внутри неё падает
        # с InFailedSqlTransaction (ТЗ п.10).
        try:
            with transaction.atomic():
                record = VoteRecord.objects.create(
                    election_id=election.id, student_id=student.id
                )
        except IntegrityError as exc:
            if _is_duplicate_vote(exc):
                # Ballot здесь принципиально не создаётся: дубликат не должен
                # добавлять бюллетень (ТЗ п.6, 10).
                raise AlreadyVotedError()
            raise

        Ballot.objects.create(election_id=election.id, candidate_id=candidate_id)

        # Положительный факт участия ставится в кэш ТОЛЬКО после COMMIT.
        # Поставить его раньше значило бы показать студенту «вы проголосовали»
        # при транзакции, которая потом откатилась (ТЗ п.21).
        #
        # Кэшируется только положительный факт: он необратим. Отрицательный
        # («ещё не голосовал») не кэшируется вовсе — устаревшее «нет» после
        # успешного голоса показало бы кнопку голосования повторно.
        # Кэшируется сама метка времени, а не флаг: ответ endpoint'а содержит
        # voted_at, и вернуть его пустым при попадании в кэш значило бы отдавать
        # разные данные в зависимости от состояния Redis.
        voted_at = record.voted_at
        transaction.on_commit(
            lambda: safe_set(
                student_vote_status(student.id, election.id),
                voted_at,
                timeout=CachePolicy.VOTE_STATUS_POSITIVE,
            )
        )

    # Логируется ПОСЛЕ коммита и без пары student+candidate: связка этих двух
    # идентификаторов в логах восстанавливает выбор студента (ТЗ п.4).
    logger.info("vote_accepted election_id=%s", election_id)

    return True
