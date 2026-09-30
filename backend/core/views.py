from django.conf import settings
from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    logout,
    update_session_auth_hash,
)
from django.db import connection, transaction
from django.http import FileResponse, Http404, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from . import serializers as s
from . import services
from .authentication import AgentAuthentication
from .models import AgentKey, AgentRole, AuditEvent, Business
from .permissions import (
    HUMAN_PERMISSIONS,
    IsAgent,
    agent_actor,
    authorize,
    human_actor,
    member_role,
)


def validated(cls, data, **kwargs):
    obj = cls(data=data, **kwargs)
    obj.is_valid(raise_exception=True)
    return obj.validated_data


def user_json(user):
    role = member_role(user)
    return {
        "id": user.pk,
        "username": user.username,
        "name": user.first_name,
        "role": role,
        "is_active": user.is_active,
        "permissions": sorted(HUMAN_PERMISSIONS.get(role, set())),
    }


def paginate(request, rows, serializer):
    try:
        page = int(request.query_params.get("page", 1))
    except (TypeError, ValueError):
        raise ValidationError("頁碼必須是正整數。")
    if page < 1:
        raise ValidationError("頁碼必須是正整數。")
    size = 30
    count = rows.count()
    return {
        "results": [serializer(row) for row in rows[(page - 1) * size : page * size]],
        "page": page,
        "pages": max(1, (count + size - 1) // size),
        "count": count,
    }


def setup_open(request):
    """A fresh local install lets the person at this computer create the first owner.

    Hosted installs use create_owner / runtime_bootstrap instead.
    """
    return (
        settings.LOCAL_APP
        and request.META.get("REMOTE_ADDR") in ("127.0.0.1", "::1")
        and not services.has_owner()
    )


class SessionView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        user = user_json(request.user) if member_role(request.user) else None
        return Response(
            {
                "user": user,
                "setup": user is None and setup_open(request),
                "csrf_token": get_token(request),
            }
        )


class LoginThrottle(AnonRateThrottle):
    scope = "login"


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginThrottle]

    @method_decorator(csrf_protect)
    def post(self, request):
        data = validated(s.LoginInput, request.data)
        user = authenticate(request, **data)
        if not member_role(user):
            raise AuthenticationFailed("帳號或密碼不正確。")
        login(request, user)
        services.audit(human_actor(user), "account.login", user)
        return Response({"user": user_json(user), "csrf_token": get_token(request)})


class SetupView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginThrottle]

    @method_decorator(csrf_protect)
    def post(self, request):
        if not setup_open(request):
            raise PermissionDenied("這個 App 已經有擁有者，請登入。")
        user = services.create_first_owner(**validated(s.LoginInput, request.data))
        login(request, user)
        return Response({"user": user_json(user), "csrf_token": get_token(request)}, status=201)


class LogoutView(APIView):
    def post(self, request):
        services.audit(human_actor(request.user), "account.logout", request.user)
        logout(request)
        return Response({"csrf_token": get_token(request)})


class PasswordView(APIView):
    def post(self, request):
        user = services.change_password(
            human_actor(request.user), **validated(s.PasswordInput, request.data)
        )
        update_session_auth_hash(request, user)
        return Response({"status": "changed", "csrf_token": get_token(request)})


class BusinessView(APIView):
    def get(self, request):
        authorize(human_actor(request.user), "business.read")
        return Response(s.BusinessSerializer(Business.current()).data)

    def patch(self, request):
        values = validated(
            s.BusinessSerializer,
            request.data,
            instance=Business.current(),
            partial=True,
        )
        return Response(
            s.BusinessSerializer(services.update_business(human_actor(request.user), values)).data
        )


class MembersView(APIView):
    def get(self, request):
        authorize(human_actor(request.user), "members.manage")

        def serialize(u):
            value = user_json(u)
            value["role"] = u.membership.role
            return value

        return Response(
            paginate(
                request,
                get_user_model()
                .objects.filter(membership__isnull=False)
                .select_related("membership")
                .order_by("id"),
                serialize,
            )
        )

    def post(self, request):
        authorize(human_actor(request.user), "members.manage")
        values = validated(s.MemberCreateInput, request.data)
        return Response(
            user_json(services.save_member(human_actor(request.user), values)),
            status=201,
        )


class MemberView(APIView):
    def patch(self, request, pk):
        authorize(human_actor(request.user), "members.manage")
        get_object_or_404(get_user_model(), pk=pk, membership__isnull=False)
        user = services.save_member(
            human_actor(request.user), validated(s.MemberUpdateInput, request.data), pk
        )
        result = user_json(user)
        result["role"] = user.membership.role
        return Response(result)


class RolesView(APIView):
    def get(self, request):
        authorize(human_actor(request.user), "agents.manage")
        return Response(
            [
                {
                    "code": r.code,
                    "label": r.label,
                    "permissions": list(r.permissions.values("code", "label", "scope")),
                }
                for r in AgentRole.objects.prefetch_related("permissions")
            ]
        )


class KeysView(APIView):
    def get(self, request):
        authorize(human_actor(request.user), "agents.manage")
        return Response(
            list(
                AgentKey.objects.order_by("-created_at").values(
                    "id",
                    "label",
                    "role_id",
                    "prefix",
                    "revoked_at",
                    "created_at",
                )
            )
        )

    def post(self, request):
        data = validated(s.KeyInput, request.data)
        key, secret = services.issue_key(human_actor(request.user), **data)
        return Response(
            {"id": key.pk, "secret": secret},
            status=201,
            headers={"Cache-Control": "no-store"},
        )


class RevokeKeyView(APIView):
    def post(self, request, pk):
        authorize(human_actor(request.user), "agents.manage")
        services.revoke_key(human_actor(request.user), get_object_or_404(AgentKey, pk=pk))
        return Response({"status": "revoked"})


class McpView(APIView):
    """How this store's Agent connects: stdio on the same computer, or HTTP /mcp."""

    def get(self, request):
        authorize(human_actor(request.user), "agents.manage")
        if settings.LOCAL_APP:
            return Response(
                {
                    "transport": "stdio",
                    "name": settings.MCP_NAME,
                    "command": "node",
                    "args": [str(settings.MCP_ENTRY), "--stdio"],
                    "env": {"CORE_API_URL": request.build_absolute_uri("/api/agent-api/")},
                    "key_env": "CORE_AGENT_KEY",
                }
            )
        return Response({"transport": "http", "url": request.build_absolute_uri("/mcp")})


class AgenrenaView(APIView):
    def get(self, request):
        return Response(services.agenrena_overview(human_actor(request.user)))


class AgenrenaConnectView(APIView):
    def post(self, request):
        result = services.start_agenrena_connection(human_actor(request.user))
        return Response(result, status=201, headers={"Cache-Control": "no-store"})


class AgenrenaCheckView(APIView):
    def post(self, request):
        return Response(services.check_agenrena_connection(human_actor(request.user)))


class AgenrenaDisconnectView(APIView):
    def post(self, request):
        services.disconnect_agenrena(human_actor(request.user))
        return Response({"status": "none"})


class AuditView(APIView):
    def get(self, request):
        authorize(human_actor(request.user), "audit.read")

        def serialize(row):
            return {
                "id": row.pk,
                "created_at": row.created_at,
                "actor_type": row.actor_type,
                "actor_label": row.actor_label,
                "action": row.action,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "customer_id": row.customer_id,
                "detail": row.detail,
            }

        return Response(paginate(request, AuditEvent.objects.all(), serialize))


class AgentView(APIView):
    authentication_classes = [AgentAuthentication]
    permission_classes = [IsAgent]


class AgentSessionView(AgentView):
    def get(self, request):
        return Response(
            {
                "role": request.auth.role_id,
                "permissions": list(request.auth.role.permissions.values_list("code", flat=True)),
            }
        )


class AgentBusinessView(AgentView):
    @transaction.atomic
    def get(self, request):
        actor = agent_actor(request.auth)
        authorize(actor, "business.read")
        obj = Business.current()
        services.audit(actor, "business.read", obj)
        return Response(s.BusinessSerializer(obj).data)


class AgentProfileView(AgentView):
    def get(self, request):
        data = validated(s.CustomerRefInput, request.query_params.dict())
        return Response(
            {"profile": services.get_customer_profile(agent_actor(request.auth), **data)}
        )

    def post(self, request):
        data = validated(s.ProfileInput, request.data)
        return Response(
            {"profile": services.update_customer_profile(agent_actor(request.auth), **data)}
        )


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


def frontend(request, path=""):
    """Local installs: Django serves the built console. Hosted installs use nginx."""
    dist = settings.FRONTEND_DIST.resolve()
    if path.startswith("assets/"):
        target = (dist / path).resolve()
        if not target.is_file() or not target.is_relative_to(dist):
            raise Http404
        response = FileResponse(target.open("rb"))
        response["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
    index = dist / "index.html"
    if not index.is_file():
        raise Http404("Frontend is not built.")
    response = FileResponse(index.open("rb"), content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    return response
