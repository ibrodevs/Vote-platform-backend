"""Middleware приложения: идентификатор запроса, метрики, заголовки кэширования."""
import logging
import os
import random
import time
import uuid

from apps.core import metrics
from apps.core.cache_policy import PRIVATE_NO_STORE, PUBLIC_SHORT

access_logger = logging.getLogger('apps.core.access')

REQUEST_ID_HEADER = 'X-Request-ID'


def _float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(0.0, min(1.0, value))


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


class RequestIDMiddleware:
    """Присваивает каждому запросу идентификатор (ТЗ п.61, 65)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = str(uuid.uuid4())
        response = self.get_response(request)
        response[REQUEST_ID_HEADER] = request.request_id
        return response


# ==============================================================================
# Cache-Control (ТЗ п.60, 96)
# ==============================================================================
# Политика по умолчанию — private/no-store, а публичным надо стать явно.

PUBLIC_PREFIXES = (
    "/api/v1/universities/",
    "/api/v1/news/",
    "/api/v1/faqs/",
    "/api/v1/pages/",
    "/api/v1/elections/recent/",
    "/api/v1/elections/public/",
    "/api/health/",
)

NEVER_PUBLIC_PREFIXES = (
    "/api/v1/admin/",
    "/api/v1/auth/",
    "/api/v1/voting/",
    "/api/v1/students/auth/",
    "/api/v1/elections/available/",
)


class CacheControlMiddleware:
    """Проставляет Cache-Control, если ответ его ещё не задал."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not response.has_header("Cache-Control"):
            response["Cache-Control"] = self._policy_for(request)
        return response

    @staticmethod
    def _policy_for(request) -> str:
        path = request.path

        if any(path.startswith(p) for p in NEVER_PUBLIC_PREFIXES):
            return PRIVATE_NO_STORE

        if request.method not in ("GET", "HEAD"):
            return PRIVATE_NO_STORE

        if request.headers.get("Authorization"):
            return PRIVATE_NO_STORE

        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return PUBLIC_SHORT

        return PRIVATE_NO_STORE


class ObservabilityMiddleware:
    """Логирование запросов и метрики (ТЗ п.61, 62).

    Счётчик запросов остаётся точным всегда. Более дорогие операции можно
    семплировать в election-day режиме через окружение:

    * HTTP_METRICS_DURATION_SAMPLE_RATE — доля запросов для Histogram;
    * HTTP_ACCESS_LOG_SAMPLE_RATE — доля INFO access-log строк;
    * HTTP_IN_PROGRESS_METRIC_ENABLED — включить Gauge активных запросов.

    По умолчанию значения 1.0/True сохраняют прежнее поведение. На пике
    рекомендуются 0.10/0.01/False: это не влияет на бизнес-логику и резко
    уменьшает mutex/file-I/O overhead Prometheus multiprocess и логирования.

    Меткой остаётся шаблон маршрута, а не фактический UUID в URL — иначе
    кардинальность временных рядов была бы неограниченной.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.duration_sample_rate = _float_env('HTTP_METRICS_DURATION_SAMPLE_RATE', 1.0)
        self.access_log_sample_rate = _float_env('HTTP_ACCESS_LOG_SAMPLE_RATE', 1.0)
        self.track_in_progress = _bool_env('HTTP_IN_PROGRESS_METRIC_ENABLED', True)

    @staticmethod
    def _sample(rate: float) -> bool:
        if rate >= 1.0:
            return True
        if rate <= 0.0:
            return False
        return random.random() < rate

    def __call__(self, request):
        started = time.perf_counter()
        if self.track_in_progress:
            metrics.http_requests_in_progress.inc()
        try:
            response = self.get_response(request)
        finally:
            if self.track_in_progress:
                metrics.http_requests_in_progress.dec()

        duration = time.perf_counter() - started
        route = self._route_of(request)
        status_code = getattr(response, 'status_code', 0)

        # Counter нужен точный: он дешёвый и используется для error-rate.
        metrics.http_requests_total.labels(
            method=request.method, route=route, status=str(status_code)
        ).inc()

        if self._sample(self.duration_sample_rate):
            metrics.http_request_duration_seconds.labels(
                method=request.method, route=route
            ).observe(duration)

        if access_logger.isEnabledFor(logging.INFO) and self._sample(self.access_log_sample_rate):
            access_logger.info(
                'request',
                extra={
                    'request_id': getattr(request, 'request_id', None),
                    'method': request.method,
                    'route': route,
                    'status': status_code,
                    'duration_ms': round(duration * 1000, 2),
                },
            )
        return response

    @staticmethod
    def _route_of(request) -> str:
        match = getattr(request, 'resolver_match', None)
        if match is not None and getattr(match, 'route', None):
            return '/' + match.route.lstrip('/')
        return '<unmatched>'
