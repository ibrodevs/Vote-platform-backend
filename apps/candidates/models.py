from django.db import models
from apps.core.models import TimeStampedUUIDModel
from apps.elections.models import Election
from apps.universities.models import University

class Candidate(TimeStampedUUIDModel):
    election = models.ForeignKey(
        Election,
        on_delete=models.CASCADE,
        related_name='candidates',
        verbose_name="Выборы"
    )
    university = models.ForeignKey(
        University,
        on_delete=models.CASCADE,
        related_name='candidates',
        verbose_name="Университет"
    )
    full_name = models.CharField(max_length=255, verbose_name="ФИО кандидата")
    photo = models.ImageField(upload_to='candidates/photos/', null=True, blank=True, verbose_name="Фотография")
    photo_url = models.CharField(max_length=500, blank=True, default='', verbose_name="Ссылка на фото")
    faculty = models.CharField(max_length=255, blank=True, default='', verbose_name="Факультет")
    course = models.PositiveSmallIntegerField(default=1, blank=True, verbose_name="Курс")
    position = models.CharField(max_length=255, blank=True, default="Кандидат", verbose_name="Должность")
    short_bio = models.TextField(blank=True, verbose_name="Краткая биография")
    program = models.TextField(blank=True, verbose_name="Предвыборная программа")
    order = models.PositiveIntegerField(default=0, verbose_name="Порядок отображения")

    class Meta:
        verbose_name = "Кандидат"
        verbose_name_plural = "Кандидаты"
        ordering = ['order', 'created_at']

    def __str__(self):
        return f"{self.full_name} ({self.election.title})"

    def save(self, *args, **kwargs):
        if self.election and not self.university_id:
            self.university = self.election.university
        super().save(*args, **kwargs)
