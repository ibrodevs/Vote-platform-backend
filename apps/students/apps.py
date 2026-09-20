from django.apps import AppConfig

class StudentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.students'

    def ready(self):
        # Регистрация сигналов аутентификации (отзыв токенов, инвалидация кэша)
        from . import signals  # noqa: F401
