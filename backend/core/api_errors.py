from django.core.exceptions import ValidationError
from django.db import IntegrityError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_handler

from .agenrena import AgenrenaError


def exception_handler(exc, context):
    if isinstance(exc, AgenrenaError):
        # Only Agenrena's error code; never tokens, secrets or response bodies.
        return Response(
            {
                "error": "agenrena_unavailable",
                "details": f"Agenrena 暫時無法完成這個操作（{exc.code}），請稍後再試。",
            },
            status=502,
        )
    if isinstance(exc, ValidationError):
        return Response(
            {
                "error": "validation_error",
                "details": getattr(exc, "message_dict", exc.messages),
            },
            status=400,
        )
    if isinstance(exc, IntegrityError):
        return Response(
            {
                "error": "conflict",
                "details": "資料已變更或名稱重複，請重新整理後再試。",
            },
            status=409,
        )
    response = drf_handler(exc, context)
    if response is not None:
        response.data = {
            "error": getattr(exc, "default_code", "invalid_request"),
            "details": response.data,
        }
    return response
