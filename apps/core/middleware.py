"""Заголовки кэширования ответов (ТЗ п.60, 96).

ЗАЧЕМ
-----
ТЗ п.60 прямо запрещает CDN-кэширование статуса голосования, профиля студента,
админского API и `POST /vote`. Запретить это технически можно только
заголовком: без него промежуточный кэш вправе сохранить ответ и отдать его
другому пользователю — то есть показать одному студенту данные другого.

Поэтому политика по умолчанию — `private, no-store`, а публичным быть надо
заслужить: endpoint попадает в белый список явно.
"""
from apps.core.cache_policy import PRIVATE_NO_STORE, PUBLIC_SHORT

# Публичные пути, одинаковые для всех посетителей. Только чтение и только
# то, что не зависит от личности запрашивающего.
PUBLIC_PREFIXES = (
    "/api/v1/universities/",
    "/api/v1/news/",
    "/api/v1/faqs/",
    "/api/v1/pages/",
    "/api/v1/elections/recent/",
    "/api/v1/elections/public/",
    "/api/health/",
)

# Пути, которые не могут быть публичными ни при каких условиях,
# даже если попадают под префикс выше.
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

        if response.has_header("Cache-Control"):
            return response

        response["Cache-Control"] = self._policy_for(request)
        return response

    @staticmethod
    def _policy_for(request) -> str:
        path = request.path

        if any(path.startswith(p) for p in NEVER_PUBLIC_PREFIXES):
            return PRIVATE_NO_STORE

        # Только безопасные методы: ответ на POST/PATCH/DELETE кэшировать нельзя
        if request.method not in ("GET", "HEAD"):
            return PRIVATE_NO_STORE

        # Запрос с авторизацией персонализирован, даже если путь публичный
        if request.headers.get("Authorization"):
            return PRIVATE_NO_STORE

        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return PUBLIC_SHORT

        return PRIVATE_NO_STORE
