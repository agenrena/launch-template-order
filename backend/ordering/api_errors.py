from core.api_errors import exception_handler as core_handler
from rest_framework.response import Response

from .services import OrderError


def exception_handler(exc, context):
    if isinstance(exc, OrderError):
        # A refusal with a sentence the caller can repeat, not a server error.
        return Response(exc.body, status=404 if exc.code == "not_found" else 409)
    return core_handler(exc, context)
