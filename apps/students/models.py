import uuid
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower, Upper
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
    auth_version = models.PositiveIntegerField(
        default=1,
        verbose_name="Версия аутентификации",
        help_text=(
            "Увеличивается при деактивации, смене пароля и security reset. "
            "Токен с устаревшей версией немедленно перестаёт действовать. "
            "Стартует с 1, чтобы отличать «версия есть» от «claim отсутствует»."
        ),
    )

    class Meta:
        verbose_name = "Студент"
        verbose_name_plural = "Студенты"
        ordering = ['full_name']
        constraints = [
            # ТЗ п.15. Регистрация проверяла Student.objects.filter(email__iexact=...)
            # перед INSERT — два параллельных запроса проходили проверку
            # одновременно. Та же гонка по природе, что была в голосовании,
            # и закрывается так же: констрейнтом базы, а не проверкой в Python.
            #
            # Условие обязательно: пустых и NULL email в базе много
            # (студенты, загруженные списком, email не имеют), и без частичного
            # индекса второй же такой студент нарушил бы уникальность.
            models.UniqueConstraint(
                Lower('email'),
                condition=~Q(email=None) & ~Q(email=''),
                name='uniq_student_email_lower',
            ),
        ]
        # Каждый индекс ниже добавлен по конкретному плану EXPLAIN,
        # снятому на 200 000 студентов. Планы до и после — в docs/PERFORMANCE.md.
        indexes = [
            # Логин: WHERE UPPER(email) = UPPER(%s) AND is_active.
            # Было: Parallel Seq Scan, 5771 буферов, 29.6 мс на каждый вход.
            models.Index(
                Upper('email'),
                name='student_email_upper_idx',
            ),
            # identify: WHERE university_id = %s AND UPPER(student_id) = UPPER(%s).
            # Было: индекс по university_id давал 10 000 строк, и все они
            # отбрасывались фильтром уже после чтения кучи.
            models.Index(
                'university',
                Upper('student_id'),
                name='student_uni_code_upper_idx',
            ),
            # Число избирателей: COUNT(*) WHERE university_id = %s AND is_active.
            # Было: Bitmap Index Scan + чтение 5771 блока кучи ради фильтра.
            models.Index(
                fields=['university', 'is_active'],
                name='student_uni_active_idx',
            ),
        ]

    # Поля, изменение которых обязано немедленно обесценить выданные токены.
    SECURITY_SENSITIVE_FIELDS = ('is_active', 'password')

    def save(self, *args, **kwargs):
        if not self.student_id:
            self.student_id = f"STU-{uuid.uuid4().hex[:8].upper()}"

        # Отзыв токенов при деактивации и смене пароля (ТЗ п.19).
        #
        # Это сделано здесь, а не в сигнале pre_save, по конкретной причине:
        # сигнал не может расширить update_fields вызывающего save(), поэтому
        # при save(update_fields=['is_active']) новая версия просто не попала бы
        # в UPDATE, и отзыв молча не сработал бы.
        #
        # Не покрывает queryset.update() и bulk_update() — они не вызывают save().
        # Для массовых операций есть services_auth.revoke_student_tokens().
        if self.pk is not None:
            previous = type(self).objects.filter(pk=self.pk).only(
                'is_active', 'password', 'auth_version'
            ).first()
            if previous is not None:
                deactivated = previous.is_active and not self.is_active
                password_changed = previous.password != self.password
                if deactivated or password_changed:
                    self.auth_version = previous.auth_version + 1
                    update_fields = kwargs.get('update_fields')
                    if update_fields is not None:
                        kwargs['update_fields'] = set(update_fields) | {'auth_version'}

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
