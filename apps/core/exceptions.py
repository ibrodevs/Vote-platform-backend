"""Обработчик исключений DRF.

D-06 (ТЗ п.65). Раньше ветка 500 формировала ответ из `str(exc)` — наружу
уходили фрагменты SQL, пути файлов и значения переменных. Для клиента это
бесполезно, для атакующего — карта внутреннего устройства.

Теперь: клиенту generic-сообщение и `request_id`, по которому поддержка
найдёт в логах полный трейсбек.
"""
import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger('apps.core.errors')

GENERIC_SERVER_ERROR = (
    "Внутренняя ошибка сервера. Попробуйте позже, "
    "а при повторении сообщите код обращения в поддержку."
)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    request = context.get('request')
    request_id = getattr(request, 'request_id', None)

    if response is not None:
        error_code = getattr(exc, 'default_code', 'error')
        if hasattr(exc, 'detail'):
            if isinstance(exc.detail, dict):
                first_key = next(iter(exc.detail))
                first_val = exc.detail[first_key]
                if isinstance(first_val, list) and first_val:
                    message = f"{first_key}: {first_val[0]}"
                else:
                    message = f"{first_key}: {first_val}"
            elif isinstance(exc.detail, list) and exc.detail:
                message = str(exc.detail[0])
            else:
                message = str(exc.detail)
        else:
            message = str(exc)

        payload = {
            "error": {
                "code": str(error_code),
                "message": message,
                "details": exc.detail if hasattr(exc, 'detail') else None,
            }
        }
        if request_id:
            payload["error"]["request_id"] = request_id
        response.data = payload
        return response

    # Необработанное исключение. Подробности — только в лог.
    logger.exception(
        "unhandled_exception request_id=%s path=%s",
        request_id,
        getattr(request, 'path', '?'),
    )
    return Response(
        {
            "error": {
                "code": "internal_server_error",
                "message": GENERIC_SERVER_ERROR,
                "details": None,
                "request_id": request_id,
            }
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
