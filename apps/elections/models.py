from django.db import models
from django.utils import timezone
from apps.core.models import TimeStampedUUIDModel
from apps.universities.models import University
from apps.accounts.models import AdminUser

class Election(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Черновик'
        SCHEDULED = 'scheduled', 'Запланированы'
        ACTIVE = 'active', 'Активны (идет голосование)'
        FINISHED = 'finished', 'Завершены'
        CANCELLED = 'cancelled', 'Отменены'

    university = models.ForeignKey(
        University,
        on_delete=models.CASCADE,
        related_name='elections',
        verbose_name="Университет"
    )
    title = models.CharField(max_length=255, verbose_name="Название выборов (RU)")
    title_ky = models.CharField(max_length=255, verbose_name="Шайлоонун аталышы (KY)")
    description = models.TextField(blank=True, verbose_name="Описание (RU)")
    description_ky = models.TextField(blank=True, verbose_name="Сүрөттөмөсү (KY)")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="Статус"
    )
    starts_at = models.DateTimeField(verbose_name="Дата и время начала")
    ends_at = models.DateTimeField(verbose_name="Дата и время окончания")
    results_visible_to_admin_before_finish = models.BooleanField(
        default=False,
        verbose_name="Результаты видны администратору до завершения"
    )
    is_featured = models.BooleanField(
        default=False,
        verbose_name="Показывать в блоке «Последние выборы»"
    )
    featured_order = models.PositiveIntegerField(
        default=0,
        verbose_name="Порядок в блоке «Последние выборы»"
    )
    cover_image = models.ImageField(
        upload_to="elections/covers/",
        null=True,
        blank=True,
        verbose_name="Обложка для карточки"
    )
    cover_image_url = models.URLField(
        blank=True,
        default="",
        verbose_name="URL обложки карточки"
    )
    created_by = models.ForeignKey(
        AdminUser,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_elections',
        verbose_name="Создатель"
    )

    class Meta:
        verbose_name = "Выборы"
        verbose_name_plural = "Выборы"
        ordering = ['-starts_at']

    def __str__(self):
        return f"{self.title} ({self.university.code}) - {self.get_status_display()}"

    @property
    def is_voting_open(self) -> bool:
        now = timezone.now()
        return self.status == self.Status.ACTIVE and self.starts_at <= now <= self.ends_at
