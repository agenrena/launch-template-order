import hashlib

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import AgentKey


class AgentAuthentication(BaseAuthentication):
    def authenticate(self, request):
        parts = request.headers.get("Authorization", "").split()
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].startswith("abc_"):
            raise AuthenticationFailed("請提供有效的 Agent 金鑰。")
        key = (
            AgentKey.objects.select_related("role")
            .filter(
                digest=hashlib.sha256(parts[1].encode()).hexdigest(),
                revoked_at__isnull=True,
            )
            .first()
        )
        if key is None:
            raise AuthenticationFailed("金鑰無效或已撤銷。")
        return None, key

    def authenticate_header(self, request):
        return "Bearer"
