from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

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

        response.data = {
            "error": {
                "code": str(error_code),
                "message": message,
                "details": exc.detail if hasattr(exc, 'detail') else None
            }
        }
    else:
        # Unhandled server exception
        response = Response(
            {
                "error": {
                    "code": "internal_server_error",
                    "message": str(exc),
                    "details": None
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    return response
