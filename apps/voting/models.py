import uuid
from django.db import models

from apps.elections.models import Election
from apps.students.models import Student
from apps.candidates.models import Candidate

# ==============================================================================
# ИНВАРИАНТЫ ТАЙНОГО ГОЛОСОВАНИЯ — НЕ НАРУШАТЬ (ТЗ п.3, 106)
# ==============================================================================
# DO NOT add student relation to Ballot
# DO NOT add candidate relation to VoteRecord
# DO NOT add a FK between Ballot and VoteRecord in either direction
# DO NOT replace database uniqueness with a cache check
# DO NOT move the core vote commit to an asynchronous queue
#
# Разделение этих двух таблиц — единственное, что обеспечивает тайну голосования.
# Любая связь между ними восстанавливает пару "студент -> кандидат".
# ==============================================================================

class VoteRecord(models.Model):
    """
    Факт участия студента в выборах.
    КРИТИЧНО: НЕ содержит информации о выбранном кандидате.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    election = models.ForeignKey(
        Election,
        on_delete=models.CASCADE,
        related_name='vote_records',
        verbose_name="Выборы"
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='vote_records',
        verbose_name="Студент"
    )
    voted_at = models.DateTimeField(auto_now_add=True, verbose_name="Время голосования")

    class Meta:
        verbose_name = "Факт участия в голосовании"
        verbose_name_plural = "Факты участия в голосовании"
        constraints = [
            # Последняя линия защиты от двойного голосования (ТЗ п.6).
            # Именно база, а не Python-проверка: проверка exists() проигрывает
            # гонке, констрейнт — нет. Имя задано явно, чтобы отличать причину
            # IntegrityError в apps/voting/services.py.
            models.UniqueConstraint(
                fields=['election', 'student'],
                name='uniq_voterecord_election_student',
            ),
        ]
        # Отдельный Index(election, student) не нужен: UNIQUE уже создаёт
        # B-tree индекс по этой паре, второй только замедлял бы записи (ТЗ п.14).

    def __str__(self):
        # Без студента: __str__ попадает в админку, логи и трейсбеки.
        # Пара "кто участвовал" отдельно безопасна, но не стоит раздавать её даром.
        return f"Участие в выборах {self.election_id}"

class Ballot(models.Model):
    """
    Анонимный избирательный бюллетень.
    КРИТИЧНО: Физически НЕ имеет связи со студентом (никакого student_id, никакого FK на VoteRecord).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    election = models.ForeignKey(
        Election,
        on_delete=models.CASCADE,
        related_name='ballots',
        verbose_name="Выборы"
    )
    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name='ballots',
        verbose_name="Выбранный кандидат"
    )
    cast_at = models.DateTimeField(auto_now_add=True, verbose_name="Время опускания бюллетеня")

    class Meta:
        verbose_name = "Анонимный бюллетень"
        verbose_name_plural = "Анонимные бюллетени"
        indexes = [
            models.Index(fields=['election', 'candidate']),
        ]

    def __str__(self):
        # Без кандидата: строка бюллетеня рядом с записью об участии в одном
        # логе восстанавливает выбор студента (ТЗ п.4).
        return f"Бюллетень в выборах {self.election_id}"
