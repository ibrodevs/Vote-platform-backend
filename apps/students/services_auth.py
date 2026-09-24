"""Выпуск и отзыв студенческих токенов (ТЗ п.18, 19).

Токен живёт 7 дней и лежит в sessionStorage фронтенда. Без механизма отзыва
отчисленный студент продолжал бы голосовать всю неделю, а отозвать токен
было бы нечем — JWT не хранится на сервере.

Решение: claim `auth_version` в токене сверяется с версией в личности студента.
Любое изменение версии мгновенно обесценивает все ранее выданные токены.
"""
import datetime
import logging

import jwt
from django.conf import settings
from django.db.models import F
from django.utils import timezone

from apps.core.cache import safe_delete
from apps.core.cache_keys import student_principal

logger = logging.getLogger(__name__)

TOKEN_TYPE = 'student'
TOKEN_LIFETIME = datetime.timedelta(days=7)


def create_student_token(student) -> str:
    """Выпускает студенческий JWT.

    Состав claim'ов — часть контракта с фронтендом и с
    apps/core/authentication.py; менять только согласованно.
    """
    now = timezone.now()
    payload = {
        'token_type': TOKEN_TYPE,
        'student_id': str(student.id),
        'university_id': str(student.university_id),
        'student_code': student.student_id,
        'auth_version': student.auth_version,
        'exp': int((now + TOKEN_LIFETIME).timestamp()),
        'iat': int(now.timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')


def invalidate_principal(student_id) -> None:
    """Убирает личность студента из кэша.

    Неудача не критична: аутентификация всё равно сверяет auth_version,
    а рассинхронизацию добьёт TTL (ТЗ п.24).
    """
    safe_delete(student_principal(student_id))


def revoke_student_tokens(student) -> int:
    """Немедленно обесценивает все выданные студенту токены.

    Инкремент через F-выражение, а не чтением и записью: два параллельных
    отзыва иначе дали бы одну версию вместо двух, и один из них потерялся бы.
    """
    from .models import Student

    Student.objects.filter(pk=student.pk).update(auth_version=F('auth_version') + 1)
    new_version = Student.objects.values_list('auth_version', flat=True).get(pk=student.pk)
    student.auth_version = new_version

    invalidate_principal(student.pk)
    # Без student_id и без каких-либо данных о голосовании
    logger.info("student_tokens_revoked auth_version=%s", new_version)
    return new_version
