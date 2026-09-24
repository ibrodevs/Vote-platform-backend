"""Health-чеки (ТЗ п.43).

ДВА РАЗНЫХ ВОПРОСА
------------------
`/health/live` отвечает на вопрос «процесс жив?» и НЕ ходит в базу.
Если liveness-проба начнёт зависеть от PostgreSQL, то при проблеме с базой
оркестратор перезапустит все приложения разом — и превратит деградацию
в полный отказ.

`/health/ready` отвечает на вопрос «можно ли слать сюда трафик?» и проверяет
зависимости. Недоступный Redis сам по себе НЕ делает приложение неготовым:
предусмотрен fallback в PostgreSQL, и снимать инстанс с балансировки
из-за потери кэша значило бы устроить отказ там, где была лишь просадка.

Все проверки с жёстким коротким таймаутом: health-чек, который сам висит,
хуже отсутствующего.
"""
import logging

from django.conf import settings
from django.db import connection
from django.http import JsonResponse

from apps.core.cache import cache_available

logger = logging.getLogger(__name__)


def liveness(request):
    """Процесс жив. Никаких запросов в базу."""
    return JsonResponse({"status": "alive"})


def readiness(request):
    """Готов принимать трафик."""
    checks = {}
    ready = True

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception as exc:
        # Без базы работать нельзя: голос физически некуда записать
        checks["database"] = "unavailable"
        ready = False
        logger.error("readiness_database_failed error=%s", type(exc).__name__)

    # Состояние Redis сообщается, но на готовность не влияет (ТЗ п.43)
    checks["cache"] = "ok" if cache_available() else "degraded"

    checks["config"] = "ok"
    if settings.IS_PRODUCTION:
        from apps.core.system_checks import run_all

        failures = [r.code for r in run_all(skip={'check_migrations'}) if not r.ok]
        if failures:
            checks["config"] = f"invalid: {', '.join(failures)}"
            ready = False

    return JsonResponse(
        {"status": "ready" if ready else "not_ready", "checks": checks},
        status=200 if ready else 503,
    )
