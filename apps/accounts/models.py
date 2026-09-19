import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from apps.universities.models import University

class AdminUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email адрес обязателен')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', AdminUser.Role.SUPER_ADMIN)
        return self.create_user(email, password, **extra_fields)

class AdminUser(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        SUPER_ADMIN = 'super_admin', 'Супер-администратор'
        UNIVERSITY_ADMIN = 'university_admin', 'Администратор университета'
        OBSERVER = 'observer', 'Сотрудник (только просмотр)'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, verbose_name="Email")
    full_name = models.CharField(max_length=255, verbose_name="ФИО")
    role = models.CharField(
        max_length=30,
        choices=Role.choices,
        default=Role.UNIVERSITY_ADMIN,
        verbose_name="Роль"
    )
    university = models.ForeignKey(
        University,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='administrators',
        verbose_name="Университет"
    )
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    is_staff = models.BooleanField(default=True, verbose_name="Доступ к админке")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлен")

    objects = AdminUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    class Meta:
        verbose_name = "Администратор"
        verbose_name_plural = "Администраторы"

    def __str__(self):
        return f"{self.full_name} ({self.email}) - {self.get_role_display()}"

class AdminActionLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admin = models.ForeignKey(
        AdminUser,
        on_delete=models.SET_NULL,
        null=True,
        related_name='action_logs',
        verbose_name="Администратор"
    )
    action = models.CharField(max_length=100, verbose_name="Действие")
    target_type = models.CharField(max_length=50, blank=True, verbose_name="Тип объекта")
    target_id = models.CharField(max_length=100, blank=True, verbose_name="ID объекта")
    details = models.JSONField(default=dict, blank=True, verbose_name="Детали")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP-адрес")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Время действия")

    class Meta:
        verbose_name = "Лог действий администратора"
        verbose_name_plural = "Логи действий администратора"
        ordering = ['-created_at']

    def __str__(self):
        admin_email = self.admin.email if self.admin else "System"
        return f"[{self.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {admin_email} - {self.action}"
