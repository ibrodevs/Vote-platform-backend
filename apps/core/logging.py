"""Structured logging (ТЗ п.61, 4).

ПОЧЕМУ JSON
-----------
При нескольких репликах и десятках тысяч запросов в секунду разбирать
текстовые строки глазами невозможно. JSON позволяет отфильтровать по
`request_id` и увидеть всю историю одного запроса, а не искать её grep'ом
по трём файлам.

ЧТО НИКОГДА НЕ ПОПАДАЕТ В ЛОГ
-----------------------------
`Authorization` — в нём токен, по которому можно действовать от имени студента.
Пароли и их хэши. Коды подтверждения. И главное: выбор кандидата в любом виде.

Последнее — не перестраховка. Запись «студент X проголосовал» и запись
«подан голос за кандидата Y» с близкими метками времени в одном логе
восстанавливают пару «кто за кого» без всякого взлома. Именно поэтому
`apps/voting/services.py` пишет только `vote_accepted election_id=...`.

Фильтр ниже вырезает запрещённые поля, даже если их попробуют залогировать:
одного правила в документации мало, нужен механизм.
"""
import json
import logging
import os
import re
import socket

INSTANCE = os.getenv('INSTANCE_NAME') or socket.gethostname()

# Поля, которые вырезаются из любой записи лога
FORBIDDEN_KEYS = frozenset({
    'authorization', 'password', 'passwd', 'secret', 'token', 'api_key',
    'code', 'otp', 'candidate_id', 'candidate', 'student_id', 'student',
    'access', 'refresh', 'student_token',
})

REDACTED = '[вырезано]'

# Значения, похожие на секреты, вырезаются из текста сообщения
_BEARER_RE = re.compile(r'(Bearer\s+)[A-Za-z0-9._\-]+', re.IGNORECASE)
_JWT_RE = re.compile(r'\beyJ[A-Za-z0-9._\-]{20,}')


def scrub_text(value: str) -> str:
    """Вырезает токены из свободного текста."""
    value = _BEARER_RE.sub(r'\1' + REDACTED, value)
    return _JWT_RE.sub(REDACTED, value)


def scrub_mapping(data: dict) -> dict:
    """Вырезает запрещённые ключи, рекурсивно."""
    cleaned = {}
    for key, value in data.items():
        if str(key).lower() in FORBIDDEN_KEYS:
            cleaned[key] = REDACTED
        elif isinstance(value, dict):
            cleaned[key] = scrub_mapping(value)
        elif isinstance(value, str):
            cleaned[key] = scrub_text(value)
        else:
            cleaned[key] = value
    return cleaned


class JSONFormatter(logging.Formatter):
    """Одна строка JSON на событие."""

    def format(self, record):
        payload = {
            'ts': self.formatTime(record, '%Y-%m-%dT%H:%M:%S%z'),
            'level': record.levelname,
            'logger': record.name,
            'message': scrub_text(record.getMessage()),
            'instance': INSTANCE,
        }

        for attr in ('request_id', 'method', 'route', 'status', 'duration_ms'):
            value = getattr(record, attr, None)
            if value is not None:
                payload[attr] = value

        extra = getattr(record, 'context', None)
        if isinstance(extra, dict):
            payload['context'] = scrub_mapping(extra)

        if record.exc_info:
            payload['exception'] = scrub_text(self.formatException(record.exc_info))

        return json.dumps(payload, ensure_ascii=False, default=str)


class SensitiveDataFilter(logging.Filter):
    """Последний рубеж: вырезает секреты из args записи.

    Существует потому, что запрет «не логировать токен» соблюдается людьми,
    а механизм — всегда.
    """

    def filter(self, record):
        if isinstance(record.args, dict):
            record.args = scrub_mapping(record.args)
        elif isinstance(record.args, tuple):
            record.args = tuple(
                scrub_text(a) if isinstance(a, str) else a for a in record.args
            )
        return True
