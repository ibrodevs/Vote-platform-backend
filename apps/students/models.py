import uuid
from django.db import models
from apps.core.models import TimeStampedUUIDModel
from apps.universities.models import University
from apps.accounts.models import AdminUser

class UploadBatch(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        PROCESSING = 'processing', 'В обработке'
        COMPLETED = 'completed', 'Завершено'
        FAILED = 'failed', 'Ошибка'

    university = models.ForeignKey(
        University,
        on_delete=models.CASCADE,
        related_name='upload_batches',
        verbose_name="Университет"
    )
    uploaded_by = models.ForeignKey(
        AdminUser,
        on_delete=models.SET_NULL,
        null=True,
        related_name='uploaded_batches',
        verbose_name="Загрузил"
    )
    file_name = models.CharField(max_length=255, verbose_name="Имя файла")
    total_rows = models.PositiveIntegerField(default=0, verbose_name="Всего строк")
    success_count = models.PositiveIntegerField(default=0, verbose_name="Успешно импортировано")
    error_count = models.PositiveIntegerField(default=0, verbose_name="Количество ошибок")
    errors_detail = models.JSONField(default=list, blank=True, verbose_name="Детали ошибок")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PROCESSING,
        verbose_name="Статус"
    )

    class Meta:
        verbose_name = "Пакет загрузки студентов"
        verbose_name_plural = "Пакеты загрузки студентов"
        ordering = ['-created_at']

    def __str__(self):
        return f"Пакет {self.file_name} ({self.university.name}) - {self.get_status_display()}"

class Student(TimeStampedUUIDModel):
    university = models.ForeignKey(
        University,
        on_delete=models.CASCADE,
        related_name='students',
        verbose_name="Университет"
    )
    student_id = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name="Номер/код студента"
    )
    full_name = models.CharField(max_length=255, verbose_name="ФИО студента")
    photo = models.ImageField(upload_to='students/photos/', null=True, blank=True, verbose_name="Фотография")
    phone_number = models.CharField(max_length=50, blank=True, default='', verbose_name="Номер телефона")
    email = models.EmailField(null=True, blank=True, verbose_name="Email")
    password = models.CharField(max_length=255, blank=True, default='', verbose_name="Хэш пароля")
    faculty = models.CharField(max_length=255, blank=True, default='', verbose_name="Факультет")
    group = models.CharField(max_length=100, blank=True, default='', verbose_name="Группа")
    course = models.PositiveSmallIntegerField(verbose_name="Курс", default=1)
    uploaded_batch = models.ForeignKey(
        UploadBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='students',
        verbose_name="Пакет загрузки"
    )
    is_active = models.BooleanField(default=True, verbose_name="Активен")

    class Meta:
        verbose_name = "Студент"
        verbose_name_plural = "Студенты"
        ordering = ['full_name']

    def save(self, *args, **kwargs):
        if not self.student_id:
            self.student_id = f"STU-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} ({self.student_id}) - {self.university.code}"

class StudentAuthSession(TimeStampedUUIDModel):
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='auth_sessions',
        verbose_name="Студент"
    )
    phone_number = models.CharField(max_length=50, verbose_name="Номер телефона")
    code = models.CharField(max_length=10, verbose_name="Код подтверждения")
    attempts = models.PositiveSmallIntegerField(default=0, verbose_name="Попытки")
    is_verified = models.BooleanField(default=False, verbose_name="Подтвержден")
    expires_at = models.DateTimeField(verbose_name="Истекает в")

    class Meta:
        verbose_name = "Сессия аутентификации студента"
        verbose_name_plural = "Сессии аутентификации студентов"
        ordering = ['-created_at']

    def __str__(self):
        return f"OTP для {self.student.full_name} ({self.code}) - {'OK' if self.is_verified else 'Pending'}"
