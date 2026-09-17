import uuid
from django.db import models
from apps.elections.models import Election
from apps.students.models import Student
from apps.candidates.models import Candidate

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
        unique_together = ('election', 'student')
        indexes = [
            models.Index(fields=['election', 'student']),
        ]

    def __str__(self):
        return f"Студент {self.student.student_id} проголосовал в {self.election.title}"

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
        return f"Анонимный голос за {self.candidate.full_name} в {self.election.title}"
