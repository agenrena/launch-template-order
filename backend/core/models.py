"""One store per App and database. Business templates own their additional models.

The store is the Business: on Agenrena it is one Business Profile with one
customer-service agent, and this App is its software. The App is also the
store's Agenrena Vendor; its credentials come only from the environment and the
store grants it once (AgenrenaConnection).
"""

import hashlib
import secrets
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def valid_timezone(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError("請使用有效時區，例如 Asia/Taipei。")


class Record(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class Business(models.Model):
    """The store. A chain runs one App per store."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    name = models.CharField(max_length=120, default="我的商家")
    about = models.TextField(max_length=2000, blank=True)
    address = models.CharField(max_length=300, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    timezone = models.CharField(max_length=64, default="Asia/Taipei", validators=[valid_timezone])

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="one_business")]

    @classmethod
    def current(cls):
        return cls.objects.get_or_create(pk=1)[0]


class Membership(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="membership"
    )
    role = models.CharField(
        max_length=16,
        choices=[("owner", "擁有者"), ("admin", "管理員")],
        default="admin",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=["owner", "admin"]), name="valid_human_role"
            )
        ]


class CustomerIdentity(Record):
    """Identity link only, not a CRM. Domain records reference this internal ID.

    An authorized Agent supplies the stable reference from Agenrena conversation
    context. We trust that Agent; the reference itself is not a signed credential.
    Agenrena issues a different reference per store, so the same person at
    another store (another App) is someone else there.
    """

    display_name = models.CharField(max_length=120, blank=True)
    agenrena_customer_ref = models.CharField(max_length=36, null=True, blank=True, unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(agenrena_customer_ref__isnull=True)
                | ~models.Q(agenrena_customer_ref=""),
                name="identity_reference_not_empty",
            )
        ]


class AgentPermission(models.Model):
    code = models.CharField(max_length=80, primary_key=True)
    label = models.CharField(max_length=120)
    scope = models.CharField(
        max_length=16, choices=[("business", "商家公開資料"), ("customer", "當前顧客")]
    )

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(scope__in=["business", "customer"]),
                name="valid_agent_scope",
            )
        ]


class AgentRole(models.Model):
    code = models.SlugField(primary_key=True)
    label = models.CharField(max_length=120)
    permissions = models.ManyToManyField(AgentPermission)

    class Meta:
        ordering = ["code"]


class AgentKey(Record):
    label = models.CharField(max_length=80)
    role = models.ForeignKey(AgentRole, on_delete=models.PROTECT)
    prefix = models.CharField(max_length=12)
    digest = models.CharField(max_length=64, unique=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def issue(cls, label, role):
        secret = "abc_" + secrets.token_urlsafe(32)
        return cls.objects.create(
            label=label,
            role=role,
            prefix=secret[:12],
            digest=hashlib.sha256(secret.encode()).hexdigest(),
        ), secret


class AgenrenaConnection(models.Model):
    """The store's grant: its Agenrena Business Profile lets this App speak for it.

    At most one row. Only ``messages:send`` is requested. No row means not
    connected; a pending row holds the consent session being polled.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    status = models.CharField(
        max_length=12,
        choices=[("pending", "等待授權"), ("connected", "已連接"), ("revoked", "已失效")],
    )
    session_id = models.UUIDField(null=True, blank=True)
    session_expires_at = models.DateTimeField(null=True, blank=True)
    grant_id = models.CharField(max_length=64, blank=True)
    business_name = models.CharField(max_length=200, blank=True)
    connected_at = models.DateTimeField(null=True, blank=True)
    connected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="one_agenrena_connection"),
            models.CheckConstraint(
                condition=models.Q(status__in=["pending", "connected", "revoked"]),
                name="valid_agenrena_status",
            ),
        ]

    @classmethod
    def current(cls):
        return cls.objects.filter(pk=1).first()


class AuditEvent(Record):
    actor_type = models.CharField(max_length=12)
    actor_id = models.CharField(max_length=150)
    actor_label = models.CharField(max_length=150)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=80, blank=True)
    target_id = models.CharField(max_length=150, blank=True)
    customer = models.ForeignKey(CustomerIdentity, null=True, on_delete=models.PROTECT)
    detail = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at", "-id"]
