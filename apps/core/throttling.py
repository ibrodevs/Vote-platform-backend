"""Ограничение частоты запросов (ТЗ п.36).

ГЛАВНАЯ ОПАСНОСТЬ: ЗАБЛОКИРОВАТЬ ЦЕЛЫЙ УНИВЕРСИТЕТ
---------------------------------------------------
Студенты голосуют из университетской сети, за одним внешним IP. Лимит
по IP, рассчитанный на одного человека, остановит голосование для пяти
тысяч студентов сразу — и выглядеть это будет как атака, хотя это
обычный день выборов.

Поэтому ключ выбирается по смыслу endpoint'а:
  * есть аутентифицированный студент -> ключ по студенту (голосование,
    статус, профиль). IP не участвует вовсе;
  * студента ещё нет -> ключ по IP, но только для операций, которые
    и должны быть редкими: вход, регистрация, запрос и проверка кода.

Волюметрические атаки останавливаются раньше — на Nginx и WAF
(deploy/nginx.conf). Здесь защита от перебора, а не от флуда.

ОТКЛЮЧЕНИЕ ДЛЯ НАГРУЗОЧНОГО ТЕСТИРОВАНИЯ
----------------------------------------
`RATE_LIMIT_ENABLED=False` снимает все лимиты. Без этого бенчмарк этапа 10
измерял бы работу троттлера, а не приложения.
"""
from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class _ConfigurableThrottle(SimpleRateThrottle):
    """База: уважает общий выключатель и берёт порог из настроек."""

    def get_rate(self):
        return settings.RATE_LIMITS.get(self.scope, None)

    def allow_request(self, request, view):
        if not settings.RATE_LIMIT_ENABLED:
            return True
        return super().allow_request(request, view)


class StudentActionThrottle(_ConfigurableThrottle):
    """Ключ — студент, не IP.

    Используется там, где студент уже аутентифицирован. Пять тысяч студентов
    за одним NAT получают пять тысяч независимых лимитов, а один студент,
    отправляющий сотни POST подряд, упирается в свой (ТЗ п.36).
    """

    scope = 'student_action'

    def get_cache_key(self, request, view):
        student_id = getattr(request.user, 'id', None)
        if not getattr(request.user, 'is_student', False) or not student_id:
            return None  # не студент — этот троттл не применяется
        return self.cache_format % {'scope': self.scope, 'ident': student_id}


class VoteThrottle(StudentActionThrottle):
    """Отдельный порог для голосования.

    Голос в норме один. Сотни попыток от одного студента — либо ошибка
    клиента, либо попытка нащупать гонку.
    """

    scope = 'vote'


class AuthAttemptThrottle(_ConfigurableThrottle):
    """Ключ — IP. Только для операций до аутентификации.

    Здесь IP оправдан: вход, регистрация и запрос кода в норме редки даже
    для целого университета, а перебор пароля идёт именно с одного адреса.
    """

    scope = 'auth_attempt'

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }


class OtpVerifyThrottle(AuthAttemptThrottle):
    """Проверка кода — самый привлекательный для перебора endpoint.

    Счётчик попыток в самой сессии ограничивает перебор ОДНОГО кода;
    этот лимит ограничивает перебор по многим сессиям сразу.
    """

    scope = 'otp_verify'
