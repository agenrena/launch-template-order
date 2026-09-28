"""Human roles and MCP roles are intentionally separate. Deny by default."""

import re
from dataclasses import dataclass

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission

from .models import AgentKey, CustomerIdentity, Membership

HUMAN_PERMISSIONS = {
    "owner": frozenset(
        {
            "business.read",
            "business.write",
            "members.manage",
            "agents.manage",
            "agenrena.read",
            "agenrena.manage",
            "audit.read",
            "account.write",
        }
    ),
    "admin": frozenset(
        {
            "business.read",
            "business.write",
            "agenrena.read",
            "audit.read",
            "account.write",
        }
    ),
}


def member_role(user):
    if not user or not user.is_authenticated or not user.is_active:
        return None
    return Membership.objects.filter(user=user).values_list("role", flat=True).first()


class IsMember(BasePermission):
    def has_permission(self, request, view):
        return member_role(request.user) is not None


class IsAgent(BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.auth, AgentKey)


@dataclass(frozen=True)
class Actor:
    kind: str
    id: str
    label: str
    user: object = None
    key: object = None


def human_actor(user):
    return Actor("human", str(user.pk), user.get_username(), user=user)


def agent_actor(key):
    return Actor("agent", str(key.pk), key.label, key=key)


# Agenrena's per-store customer reference. The App sends it back to Agenrena, so
# anything else (for example an Agent-invented "guest") is refused up front.
CUSTOMER_REF = r"bcr_[0-9a-f]{32}"


def reference(value):
    if not isinstance(value, str) or not re.fullmatch(CUSTOMER_REF, value):
        raise ValidationError({"customer_ref": "請提供 Agenrena 對話附帶的有效 customer_ref。"})
    return value


def authorize(actor, permission, *, scope="business", customer_ref=None):
    if actor.kind == "human":
        if permission not in HUMAN_PERMISSIONS.get(member_role(actor.user), set()):
            raise PermissionDenied("這項操作需要擁有者或相應權限。")
    elif actor.kind == "agent":
        # Query every time so key revocation and permission edits take effect immediately.
        allowed = AgentKey.objects.filter(
            pk=actor.key.pk,
            revoked_at__isnull=True,
            role__permissions__code=permission,
            role__permissions__scope=scope,
        ).exists()
        if not allowed:
            raise PermissionDenied("Agent 權限組不允許這項操作。")
        if scope == "customer":
            return reference(customer_ref)
    else:
        raise PermissionDenied()


def scoped_customer(actor, permission, customer_ref):
    """The current customer, or None if this store has not met them yet."""
    ref = authorize(actor, permission, scope="customer", customer_ref=customer_ref)
    if actor.kind != "agent":
        raise PermissionDenied()
    return ref, CustomerIdentity.objects.filter(agenrena_customer_ref=ref).first()


# The ordering template adds service and menu operations to both human roles.
ORDERING_HUMAN_PERMISSIONS = frozenset(
    {"menu.read", "menu.write", "orders.read", "orders.manage", "ordering.settings"}
)
HUMAN_PERMISSIONS = {
    role: permissions | ORDERING_HUMAN_PERMISSIONS
    for role, permissions in HUMAN_PERMISSIONS.items()
}
