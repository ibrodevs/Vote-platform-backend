from django.db import models
from apps.core.models import TimeStampedUUIDModel

class University(TimeStampedUUIDModel):
    name = models.CharField(max_length=255, verbose_name="Название (RU)")
    name_ky = models.CharField(max_length=255, verbose_name="Аталышы (KY)")
    code = models.SlugField(max_length=50, unique=True, verbose_name="Код университета (slug)")
    logo = models.ImageField(upload_to='universities/logos/', null=True, blank=True, verbose_name="Логотип")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    is_registration_open = models.BooleanField(default=True, verbose_name="Регистрация студентов открыта")

    class Meta:
        verbose_name = "Университет"
        verbose_name_plural = "Университеты"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"

class Faculty(TimeStampedUUIDModel):
    university = models.ForeignKey(
        University,
        on_delete=models.CASCADE,
        related_name='faculties',
        verbose_name="Университет"
    )
    name = models.CharField(max_length=255, verbose_name="Название факультета (RU)")
    name_ky = models.CharField(max_length=255, blank=True, default='', verbose_name="Аталышы (KY)")
    code = models.CharField(max_length=50, blank=True, default='', verbose_name="Код/аббревиатура")

    class Meta:
        verbose_name = "Факультет"
        verbose_name_plural = "Факультеты"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.university.name})"
