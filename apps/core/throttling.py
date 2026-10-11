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
  * до аутентификации -> ключ по стабильному идентификатору попытки
    (request_id, email или student_id), а IP используется только как fallback.

Это важно в 12:00: тысячи студентов одного университета могут логиниться
через один NAT и не должны делить один счётчик. При этом перебор одного
аккаунта с разных IP всё равно попадает в один и тот же лимит.

Волюметрические атаки останавливаются раньше — на Nginx/WAF. Здесь защита
от перебора конкретной учётной записи, а не от сетевого флуда.

ОТКЛЮЧЕНИЕ ДЛЯ НАГРУЗОЧНОГО ТЕСТИРОВАНИЯ
----------------------------------------
`RATE_LIMIT_ENABLED=False` снимает все лимиты. Без этого бенчмарк этапа 10
измерял бы работу троттлера, а не приложения.
"""
import hashlib

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
            return None
        return self.cache_format % {'scope': self.scope, 'ident': student_id}


class VoteThrottle(StudentActionThrottle):
    """Отдельный порог для голосования.

    Голос в норме один. Сотни попыток от одного студента — либо ошибка
    клиента, либо попытка нащупать гонку.
    """

    scope = 'vote'


class AuthAttemptThrottle(_ConfigurableThrottle):
    """До аутентификации ограничивает конкретную учётную запись, не NAT.

    В ключ никогда не попадает исходный email/телефон/student_id: значение
    хэшируется перед записью в общий Redis. Пароль и OTP-код не читаются.
    Если endpoint не передал подходящего идентификатора, остаётся IP fallback.
    """

    scope = 'auth_attempt'

    @staticmethod
    def _stable_ident(request):
        try:
            data = request.data or {}
        except Exception:
            data = {}

        request_id = str(data.get('request_id') or '').strip().lower()
        if request_id:
            return f'request:{request_id}'

        email = str(data.get('email') or '').strip().lower()
        if email:
            return f'email:{email}'

        student_id = str(data.get('student_id') or '').strip().lower()
        university_code = str(data.get('university_code') or '').strip().lower()
        if student_id:
            return f'student:{university_code}:{student_id}'

        phone = str(data.get('phone_number') or '').strip()
        if phone:
            return f'phone:{phone}'

        return ''

    def get_cache_key(self, request, view):
        ident = self._stable_ident(request)
        if ident:
            # Короткий непрозрачный ключ: Redis не хранит PII из формы входа.
            ident = hashlib.sha256(ident.encode('utf-8')).hexdigest()[:32]
        else:
            ident = f'ip:{self.get_ident(request)}'

        return self.cache_format % {
            'scope': self.scope,
            'ident': ident,
        }


class OtpVerifyThrottle(AuthAttemptThrottle):
    """Проверка кода — самый привлекательный для перебора endpoint.

    Для verify ключом становится request_id сессии. Счётчик попыток в самой
    сессии ограничивает один код, этот throttle ограничивает частоту запросов
    к этой же сессии независимо от общего университетского NAT.
    """

    scope = 'otp_verify'
