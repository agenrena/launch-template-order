"""Shared authorization and writes. HTTP/MCP adapters never bypass this layer."""

import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import APIException, ValidationError

from . import agenrena
from .models import (
    AgenrenaConnection,
    AgentKey,
    AuditEvent,
    Business,
    CustomerIdentity,
    Membership,
)
from .permissions import Actor, authorize, human_actor, scoped_customer

logger = logging.getLogger(__name__)
# Deliveries happen after commit, outside any person's or Agent's request.
SYSTEM = Actor("system", "agenrena", "Agenrena 通知")


class Conflict(APIException):
    status_code = 409
    default_code = "conflict"


def audit(actor, action, target=None, *, customer=None, detail=None):
    # Callers supply a bounded allowlist, never request bodies, passwords or tokens.
    return AuditEvent.objects.create(
        actor_type=actor.kind,
        actor_id=actor.id,
        actor_label=actor.label,
        action=action,
        target_type=target._meta.model_name if target else "",
        target_id=str(target.pk) if target else "",
        customer=customer,
        detail=detail or {},
    )


def check_password(password, user):
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        raise ValidationError({"password": exc.messages}) from exc


def has_owner():
    return Membership.objects.filter(role="owner", user__is_active=True).exists()


@transaction.atomic
def create_first_owner(username, password):
    """First active owner of a new install. Never takes over an existing account."""
    Business.current()
    Business.objects.select_for_update().get(pk=1)
    if has_owner():
        raise Conflict("已有擁有者，請由後台管理成員。")
    User = get_user_model()
    if User.objects.filter(username=username).exists():
        raise Conflict("帳號已存在。")
    user = User(username=username)
    check_password(password, user)
    user.set_password(password)
    user.full_clean()
    user.save()
    Membership.objects.create(user=user, role="owner")
    audit(human_actor(user), "owner.initialized", user)
    return user


@transaction.atomic
def update_business(actor, values):
    authorize(actor, "business.write")
    obj = Business.current()
    for k, v in values.items():
        setattr(obj, k, v)
    obj.full_clean()
    obj.save()
    audit(actor, "business.updated", obj, detail={"fields": sorted(values)})
    return obj


@transaction.atomic
def save_member(actor, values, user_id=None):
    authorize(actor, "members.manage")
    # Serialize member changes to ensure one active owner always remains.
    Business.objects.select_for_update().get(pk=1)
    User = get_user_model()
    if user_id:
        user = User.objects.select_for_update().get(pk=user_id)
        membership = Membership.objects.get(user=user)
        role = values.get("role", membership.role)
        active = values.get("is_active", user.is_active)
        if membership.role == "owner" and user.is_active and (role != "owner" or not active):
            if (
                not Membership.objects.filter(role="owner", user__is_active=True)
                .exclude(user=user)
                .exists()
            ):
                raise ValidationError("必須保留至少一位啟用中的擁有者。")
        user.first_name = values.get("name", user.first_name)
        user.is_active = active
        membership.role = role
        user.save(update_fields=["first_name", "is_active"])
        membership.save(update_fields=["role"])
        action = "member.updated"
    else:
        user = User(username=values["username"], first_name=values.get("name", ""))
        check_password(values["password"], user)
        user.set_password(values["password"])
        user.full_clean()
        user.save()
        Membership.objects.create(user=user, role=values.get("role", "admin"))
        action = "member.created"
    audit(
        actor,
        action,
        user,
        detail={"fields": sorted(k for k in values if k != "password")},
    )
    return user


@transaction.atomic
def change_password(actor, old_password, password):
    authorize(actor, "account.write")
    user = get_user_model().objects.select_for_update().get(pk=actor.user.pk)
    if not user.check_password(old_password):
        raise ValidationError({"old_password": "目前密碼不正確。"})
    check_password(password, user)
    user.set_password(password)
    user.save(update_fields=["password"])
    audit(actor, "account.password_changed", user)
    return user


@transaction.atomic
def issue_key(actor, label, role):
    authorize(actor, "agents.manage")
    key, secret = AgentKey.issue(label, role)
    audit(actor, "agent.key_created", key, detail={"role": role.code})
    return key, secret


@transaction.atomic
def revoke_key(actor, key):
    authorize(actor, "agents.manage")
    key = AgentKey.objects.select_for_update().get(pk=key.pk)
    if key.revoked_at is None:
        key.revoked_at = timezone.now()
        key.save(update_fields=["revoked_at"])
        audit(actor, "agent.key_revoked", key)


def customer_payload(obj):
    return {"id": str(obj.pk), "display_name": obj.display_name} if obj else None


@transaction.atomic
def get_customer_profile(actor, customer_ref):
    _, obj = scoped_customer(actor, "customer.profile.read", customer_ref)
    audit(actor, "customer.profile_read", obj, customer=obj)
    return customer_payload(obj)


@transaction.atomic
def update_customer_profile(actor, customer_ref, display_name):
    ref, obj = scoped_customer(actor, "customer.profile.write", customer_ref)
    # Unique reference makes repeated/concurrent requests converge. No matching by name.
    obj, _ = CustomerIdentity.objects.get_or_create(agenrena_customer_ref=ref)
    obj = CustomerIdentity.objects.select_for_update().get(pk=obj.pk)
    obj.display_name = display_name
    obj.full_clean()
    obj.save(update_fields=["display_name"])
    audit(
        actor,
        "customer.profile_updated",
        obj,
        customer=obj,
        detail={"fields": ["display_name"]},
    )
    return customer_payload(obj)


# ---- Agenrena: the store authorizes this App (its Vendor) once ----


def agenrena_state(connection):
    if connection is None:
        return {"status": "none"}
    state = {
        "status": connection.status,
        "business_name": connection.business_name,
        "connected_at": connection.connected_at,
    }
    if connection.status == "pending":
        state["expires_at"] = connection.session_expires_at
    return state


def agenrena_overview(actor):
    authorize(actor, "agenrena.read")
    return {"configured": agenrena.configured(), **agenrena_state(AgenrenaConnection.current())}


def _require_agenrena(actor):
    authorize(actor, "agenrena.manage")
    if not agenrena.configured():
        raise ValidationError("此部署尚未設定 Agenrena Vendor 憑證，請聯絡部署管理者。")


def start_agenrena_connection(actor):
    """Return a single-use consent link for the store's Agenrena owner/admin."""
    _require_agenrena(actor)
    if AgenrenaConnection.objects.filter(status="connected").exists():
        raise Conflict("已連接 Agenrena；請先中斷連接再重新連接。")
    # The external call stays outside the transaction; no lock waits on the network.
    payload = agenrena.start_authorization()
    expires_at = parse_datetime(str(payload.get("expires_at", "")))
    if not payload.get("session_id") or not payload.get("authorize_url") or expires_at is None:
        raise agenrena.AgenrenaError("INVALID_CONSENT_RESPONSE")
    with transaction.atomic():
        business = Business.objects.select_for_update().get(pk=1)
        if AgenrenaConnection.objects.filter(status="connected").exists():
            raise Conflict("已連接 Agenrena；請先中斷連接再重新連接。")
        AgenrenaConnection.objects.update_or_create(
            pk=1,
            defaults={
                "status": "pending",
                "session_id": payload["session_id"],
                "session_expires_at": expires_at,
                "grant_id": "",
                "business_name": "",
                "connected_at": None,
                "connected_by": None,
            },
        )
        audit(actor, "agenrena.connect_started", business)
    # The link is a bearer credential for a few minutes: returned once, never stored.
    return {"authorize_url": payload["authorize_url"], "expires_at": expires_at}


def check_agenrena_connection(actor):
    """Poll the pending consent. Agenrena does not call back; this is the design."""
    _require_agenrena(actor)
    connection = AgenrenaConnection.current()
    if connection is None or connection.status != "pending":
        return agenrena_state(connection)
    session_id = connection.session_id
    payload = agenrena.authorization(session_id)
    status = payload.get("status")
    with transaction.atomic():
        business = Business.objects.select_for_update().get(pk=1)
        connection = AgenrenaConnection.objects.filter(
            status="pending", session_id=session_id
        ).first()
        if connection is None:
            return agenrena_state(AgenrenaConnection.current())
        if status == "expired":
            connection.delete()
            return {"status": "expired"}
        if status != "completed":
            return agenrena_state(connection)
        connection.status = "connected"
        connection.grant_id = str(payload.get("grant_id") or "")
        connection.business_name = str(payload.get("business_name") or "")[:200]
        connection.connected_at = timezone.now()
        connection.connected_by = actor.user
        connection.session_id = None
        connection.session_expires_at = None
        connection.save()
        audit(actor, "agenrena.connected", business)
        return agenrena_state(connection)


def disconnect_agenrena(actor):
    authorize(actor, "agenrena.manage")
    connection = AgenrenaConnection.current()
    if connection is None:
        return
    if connection.status == "connected" and agenrena.configured():
        agenrena.release_grant(connection.grant_id)
    with transaction.atomic():
        deleted, _ = AgenrenaConnection.objects.filter(
            status=connection.status, grant_id=connection.grant_id
        ).delete()
        if deleted:
            audit(actor, "agenrena.disconnected", Business.current())


def notify_customer(identity, text, *, card=None, message_id=""):
    """Tell a customer, in their Agenrena conversation with the store, about a
    fact that has just been committed. Business templates call this inside their
    writes; delivery runs after commit and can never undo or fail the write.

    ``text`` is the one-line summary (at most 200 characters with a card);
    ``card`` is ``{"status": "info|success|warning|cancelled", "header": ...,
    "content": [{"label": ..., "value": ...}]}``; a stable ``message_id`` makes
    retries of the same fact idempotent on Agenrena.
    """
    if identity is None or not identity.agenrena_customer_ref:
        return
    transaction.on_commit(
        lambda: deliver_to_customer(identity, text, card=card, message_id=message_id)
    )


def deliver_to_customer(identity, text, *, card=None, message_id=""):
    """Send now, outside a transaction. Returns whether Agenrena accepted it."""
    if not agenrena.configured() or not identity.agenrena_customer_ref:
        return False
    connection = AgenrenaConnection.objects.filter(status="connected").first()
    if connection is None:
        return False
    try:
        agenrena.send_message(
            connection.grant_id,
            identity.agenrena_customer_ref,
            text,
            card=card,
            client_message_id=message_id,
        )
    except agenrena.AgenrenaError as exc:
        if exc.code in agenrena.GRANT_GONE:
            # The store revoked this App on Agenrena. Stop until reconnected.
            AgenrenaConnection.objects.filter(
                status="connected", grant_id=connection.grant_id
            ).update(status="revoked", updated_at=timezone.now())
        logger.warning("Agenrena delivery failed: %s", exc.code)
        audit(SYSTEM, "agenrena.message_failed", customer=identity, detail={"error": exc.code})
        return False
    audit(SYSTEM, "agenrena.message_sent", customer=identity)
    return True
