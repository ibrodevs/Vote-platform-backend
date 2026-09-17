import logging
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.elections.models import Election
from apps.candidates.models import Candidate
from apps.students.models import Student
from .models import VoteRecord, Ballot

logger = logging.getLogger('apps.voting')

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

def cast_secret_ballot(student: Student, election_id: str, candidate_id: str) -> bool:
    """
    Выполняет защищенное и строго анонимное голосование в соответствии с разделом 5 ТЗ:
    - Открывается DB-транзакция.
    - Проверяется активность выборов и отсутствие VoteRecord с блокировкой строки.
    - Создается VoteRecord (election, student).
    - Создается Ballot (election, candidate) БЕЗ каких-либо ссылок на студента.
    - Раздельное логирование (запрещено логировать student_id и candidate_id вместе).
    """
    now = timezone.now()

    with transaction.atomic():
        # 1. Lock and fetch election
        try:
            election = Election.objects.select_for_update().get(id=election_id)
        except Election.DoesNotExist:
            raise VotingError("Выборы не найдены", code="election_not_found")

        # 2. Check election is active and voting window is open
        if election.status != Election.Status.ACTIVE:
            raise ElectionNotActiveError()
        if not (election.starts_at <= now <= election.ends_at):
            raise ElectionNotActiveError()

        # 3. Check student eligibility (must belong to the university)
        if election.university_id != student.university_id:
            raise IneligibleStudentError()

        # 4. Check if student has already voted with select_for_update
        existing_vote = VoteRecord.objects.select_for_update().filter(
            election=election,
            student=student
        ).exists()
        if existing_vote:
            raise AlreadyVotedError()

        # 5. Check candidate validity
        try:
            candidate = Candidate.objects.get(id=candidate_id, election=election)
        except Candidate.DoesNotExist:
            raise InvalidCandidateError()

        # 6. Record student participation (NO candidate information)
        try:
            VoteRecord.objects.create(
                election=election,
                student=student
            )
        except IntegrityError:
            raise AlreadyVotedError()

        # 7. Record secret ballot (NO student information)
        Ballot.objects.create(
            election=election,
            candidate=candidate
        )

    # 8. Decoupled audit logging - STRICT: never output student_id & candidate_id together
    logger.info(f"AUDIT_PARTICIPATION: Student {student.id} recorded participation in election {election_id}")
    logger.info(f"AUDIT_BALLOT: Anonymous ballot deposited in election {election_id} for candidate {candidate_id}")

    return True
