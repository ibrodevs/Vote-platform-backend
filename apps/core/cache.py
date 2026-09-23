"""Безопасные обёртки над кэшем (ТЗ п.20).

Redis — ускоритель, а не источник истины. Ни один вызов отсюда не должен
уметь уронить запрос: при любой проблеме с кэшем вызывающий код обязан
просто пойти в PostgreSQL.

Ловится Exception, а не только redis.RedisError: недоступный сервер,
таймаут сокета, исчерпанный пул, сбой резолвинга DNS и ошибка сериализации
дают разные классы исключений, и уронить запрос не должен ни один из них.
"""
import logging
from typing import Any, Optional

from django.core.cache import BaseCache, caches

from apps.core import cache_keys

logger = logging.getLogger(__name__)

_SENTINEL = object()


def _cache() -> BaseCache:
    return caches["default"]


def safe_get(key: str, default: Any = None) -> Any:
    """Читает из кэша. При любой ошибке возвращает default."""
    try:
        value = _cache().get(key, _SENTINEL)
    except Exception:
        logger.warning("cache_get_failed key=%s", key, exc_info=True)
        return default
    return default if value is _SENTINEL else value


def safe_set(key: str, value: Any, timeout: Optional[int] = None) -> bool:
    """Пишет в кэш. Возвращает True, если запись удалась."""
    try:
        _cache().set(key, value, timeout=timeout)
        return True
    except Exception:
        logger.warning("cache_set_failed key=%s", key, exc_info=True)
        return False


def safe_delete(key: str) -> bool:
    """Удаляет запись. Возвращает True, если удаление прошло без ошибки.

    Неудача здесь означает, что устаревшее значение могло остаться в кэше.
    Поэтому для критичных данных TTL — обязательная вторая линия (ТЗ п.24).
    """
    try:
        _cache().delete(key)
        return True
    except Exception:
        logger.warning("cache_delete_failed key=%s", key, exc_info=True)
        return False


def cache_available() -> bool:
    """Проверка живости кэша для health-check (ТЗ п.43)."""
    try:
        _cache().set(f"{cache_keys.NAMESPACE}:healthcheck", "1", timeout=5)
        return True
    except Exception:
        return False
