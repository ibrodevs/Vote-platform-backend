"""Middleware приложения: идентификатор запроса, метрики, заголовки кэширования."""
import logging
import time
import uuid

from apps.core import metrics
from apps.core.cache_policy import PRIVATE_NO_STORE, PUBLIC_SHORT

access_logger = logging.getLogger('apps.core.access')

REQUEST_ID_HEADER = 'X-Request-ID'


class RequestIDMiddleware:
    """Присваивает каждому запросу идентификатор (ТЗ п.61, 65).

    Нужен для двух вещей сразу: клиент получает его в ответе на ошибку
    и может назвать поддержке, а в логах по нему собирается вся история
    запроса. Без него сообщение «внутренняя ошибка» бесполезно обеим сторонам.

    Идентификатор всегда генерируется сервером и никогда не берётся из
    входящего заголовка: иначе клиент мог бы подставить чужой id и запутать
    разбор инцидента, а то и засорить логи выбранной строкой.
    """

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
# ТЗ п.60 прямо запрещает CDN-кэширование статуса голосования, профиля
# студента, админского API и POST /vote. Технически запретить это можно
# только заголовком: без него промежуточный кэш вправе сохранить ответ
# и отдать его другому пользователю.
#
# Поэтому политика по умолчанию — private/no-store, а публичным надо стать явно.

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
    """Проставляет Cache-Control, если ответ его ещё не задал.

    Уже выставленный заголовок не трогается: если вьюха явно решила,
    как кэшировать свой ответ, она знает лучше.
    """

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

        # Ответ на POST/PATCH/DELETE кэшировать нельзя
        if request.method not in ("GET", "HEAD"):
            return PRIVATE_NO_STORE

        # Запрос с авторизацией персонализирован, даже если путь публичный
        if request.headers.get("Authorization"):
            return PRIVATE_NO_STORE

        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return PUBLIC_SHORT

        return PRIVATE_NO_STORE


class ObservabilityMiddleware:
    """Логирование запросов и метрики (ТЗ п.61, 62).

    МЕТКОЙ ИДЁТ ШАБЛОН МАРШРУТА, А НЕ ПУТЬ
    ---------------------------------------
    `/api/v1/elections/<uuid:pk>/`, а не `/api/v1/elections/3f2a.../`.
    Путь с подставленным идентификатором порождал бы отдельный временной
    ряд на каждые выборы и каждого кандидата — Prometheus не пережил бы
    и суток.

    Тело запроса и заголовки не пишутся ни при каких условиях:
    в Authorization токен, в теле POST /vote — выбор студента (ТЗ п.4).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        metrics.http_requests_in_progress.inc()
        try:
            response = self.get_response(request)
        finally:
            metrics.http_requests_in_progress.dec()

        duration = time.perf_counter() - started
        route = self._route_of(request)
        status_code = getattr(response, 'status_code', 0)

        metrics.http_requests_total.labels(
            method=request.method, route=route, status=str(status_code)
        ).inc()
        metrics.http_request_duration_seconds.labels(
            method=request.method, route=route
        ).observe(duration)

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
        # Маршрут не разрешился (404). Возвращается константа, а не путь:
        # иначе любой сканер, перебирающий адреса, раздул бы кардинальность.
        return '<unmatched>'
