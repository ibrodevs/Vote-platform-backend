"""Аутентификация студентов и администраторов.

ГОРЯЧИЙ ПУТЬ СТУДЕНТА (ТЗ п.18)
-------------------------------
Раньше каждый authenticated-запрос делал SELECT Student с JOIN на University.
При 40k RPS это 40k запросов в секунду в базу только ради того, чтобы узнать,
кто пришёл.

Теперь: подпись JWT проверяется локально, личность берётся из Redis.
Промах стоит один SELECT и заполняет кэш. Redis недоступен — идём в PostgreSQL
и работаем дальше: кэш здесь ускоритель, а не условие работоспособности (ТЗ п.20).

ОТЗЫВ (ТЗ п.19)
---------------
JWT нельзя отозвать сам по себе, поэтому в токене есть claim auth_version.
Он сверяется с версией студента; расхождение = токен мёртв. Версия растёт
при деактивации, смене пароля и явном отзыве (apps/students/signals.py).
"""
import logging
from typing import Any, Optional

import jwt
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.core.cache import safe_get, safe_set
from apps.core.cache_keys import student_principal as principal_key
from apps.core.principals import StudentPrincipal

logger = logging.getLogger(__name__)

# D-06: наружу уходит только это. Подробности исключения — в лог; клиенту
# они не помогают, а атакующему подсказывают устройство системы (ТЗ п.65).
GENERIC_AUTH_ERROR = "Недействительный токен авторизации"


class StudentUserWrapper:
    """Представляет студента как request.user для DRF.

    Горячие пути обязаны использовать поля принципала (id, university_id).
    Свойство `student` подгружает полную модель ЛЕНИВО и стоит одного SELECT —
    оно для профиля и прочих нечастых мест, не для голосования.
    """

    def __init__(self, principal: StudentPrincipal):
        self.principal = principal
        self.id = principal.id
        self.student_id = principal.student_code
        self.student_code = principal.student_code
        self.full_name = principal.full_name
        self.university_id = principal.university_id
        self.is_student = True
        self.is_authenticated = True
        self.is_staff = False
        self.is_superuser = False
        self._student = None

    @property
    def student(self):
        if self._student is None:
            from apps.students.models import Student
            self._student = Student.objects.select_related('university').get(id=self.id)
        return self._student

    @property
    def university(self):
        return self.student.university

    def __str__(self) -> str:
        return f"Student: {self.full_name} ({self.student_code})"


def _load_principal(student_id: str) -> Optional[StudentPrincipal]:
    """Личность студента: сначала кэш, при промахе — база.

    Возвращает (principal | None, from_cache: bool).
    """
    key = principal_key(student_id)

    cached = StudentPrincipal.from_cache(safe_get(key))
    if cached is not None:
        return cached, True

    from apps.students.models import Student
    try:
        student = Student.objects.only(
            'id', 'student_id', 'university_id', 'full_name', 'is_active', 'auth_version'
        ).get(id=student_id)
    except (Student.DoesNotExist, ValueError, TypeError):
        return None, False

    principal = StudentPrincipal.from_model(student)
    safe_set(key, principal.to_cache(), timeout=settings.AUTH_PRINCIPAL_CACHE_TTL)
    return principal, False


def _reload_principal_from_db(student_id: str) -> Optional[StudentPrincipal]:
    """Перечитывает личность в обход кэша.

    Нужно, когда версия в кэше не сошлась с токеном: запись могла устареть,
    и отзыв не должен зависеть от того, дошла ли инвалидация до Redis.
    """
    from apps.students.models import Student
    try:
        student = Student.objects.only(
            'id', 'student_id', 'university_id', 'full_name', 'is_active', 'auth_version'
        ).get(id=student_id)
    except (Student.DoesNotExist, ValueError, TypeError):
        return None

    principal = StudentPrincipal.from_model(student)
    safe_set(principal_key(student_id), principal.to_cache(),
             timeout=settings.AUTH_PRINCIPAL_CACHE_TTL)
    return principal


class CombinedJWTAuthentication(BaseAuthentication):
    """Различает студенческий JWT и админский SimpleJWT."""

    def __init__(self) -> None:
        self.simplejwt_auth = JWTAuthentication()

    def authenticate(self, request: Request) -> Optional[tuple[Any, None]]:
        header = request.headers.get('Authorization')
        if not header:
            return None

        parts = header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return None

        raw_token = parts[1]

        try:
            payload = jwt.decode(raw_token, settings.SECRET_KEY, algorithms=['HS256'])
            if payload.get('token_type') == 'student':
                return self._authenticate_student(payload), raw_token
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed("Срок действия студенческого токена истёк")
        except jwt.InvalidTokenError:
            pass  # возможно, это админский токен — пробуем ниже

        try:
            validated_token = self.simplejwt_auth.get_validated_token(raw_token)
            user = self.simplejwt_auth.get_user(validated_token)
            user.is_student = False
            return (user, validated_token)
        except Exception:
            # D-06: str(e) наружу не уходит
            logger.info("admin_token_rejected", exc_info=True)
            raise AuthenticationFailed(GENERIC_AUTH_ERROR)

    def _authenticate_student(self, payload: dict[str, Any]) -> StudentUserWrapper:
        student_id = payload.get('student_id')
        if not student_id:
            raise AuthenticationFailed(GENERIC_AUTH_ERROR)

        principal, from_cache = _load_principal(student_id)
        if principal is None:
            raise AuthenticationFailed("Студент не найден")

        token_version = payload.get('auth_version')
        principal = self._verify_auth_version(principal, token_version, from_cache)

        # D-04: деактивированный студент раньше продолжал работать всю неделю
        # жизни токена. Проверка идёт до сверки версий: отключённый аккаунт
        # не должен пройти даже с идеально свежим токеном.
        if not principal.is_active:
            raise AuthenticationFailed("Учётная запись студента деактивирована")

        return StudentUserWrapper(principal)

    def _verify_auth_version(
        self,
        principal: StudentPrincipal,
        token_version: Optional[int],
        from_cache: bool,
    ) -> StudentPrincipal:
        if token_version is None:
            # Токены, выпущенные до появления claim'а, обязаны дожить свой срок:
            # иначе обновление backend'а разлогинило бы всех разом (ТЗ п.19).
            if settings.STUDENT_TOKEN_ALLOW_MISSING_AUTH_VERSION:
                return principal
            raise AuthenticationFailed(GENERIC_AUTH_ERROR)

        if token_version == principal.auth_version:
            return principal

        # Версия не сошлась. Запись в кэше могла устареть — перечитываем из базы,
        # чтобы отзыв не зависел от того, дошла ли инвалидация до Redis.
        if from_cache:
            fresh = _reload_principal_from_db(principal.id)
            if fresh is not None and token_version == fresh.auth_version:
                return fresh
            if fresh is not None:
                principal = fresh

        logger.info("student_token_revoked_version_mismatch")
        raise AuthenticationFailed("Сессия завершена. Войдите заново")
