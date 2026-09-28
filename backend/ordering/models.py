"""Ordering for one store, using the local copy of Business Core.

Two levels, and the split is the point. A **Tab** is the bill: one per table for
as long as that party sits there, one per collection for takeout. A **Round** is
one press of the send button, and the status machine hangs off it: the shop
confirms, refuses or completes a batch of food, not a table.

Names and prices are copied onto order lines. A menu is edited while earlier
orders are still open, and a line that read its price through the menu would
quietly restate what somebody already agreed to pay.
"""

import hashlib
import secrets
from decimal import Decimal

from core.models import CustomerIdentity, Record
from django.db import models, transaction
from django.utils import timezone


class OrderingSettings(models.Model):
    """How this store takes orders."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    # A code, not a symbol: `$` is six different currencies. Never converted.
    currency = models.CharField(max_length=3, default="TWD")
    accepts_dine_in = models.BooleanField(default=True)
    accepts_takeout = models.BooleanField(default=True)
    # Minutes before closing that the kitchen stops taking orders. An offset, so
    # a store that shuts at 21:00 on weekdays and 22:00 at weekends has one rule.
    last_order_minutes_before_close = models.PositiveIntegerField(default=0)
    # The store's short id on Agenrena, for the "ask the store" link on every
    # customer page. Blank means no link rather than a broken one.
    agenrena_short_id = models.CharField(max_length=32, blank=True)
    # "We're swamped": stops new orders at every entrance for a while or until
    # resumed. Orders already sent are unaffected. Expiry needs no scheduler:
    # every check compares against the time.
    orders_paused = models.BooleanField(default=False)
    paused_until = models.DateTimeField(null=True, blank=True)
    pause_reason = models.CharField(max_length=120, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="one_ordering_settings")
        ]

    def is_paused(self, when=None):
        return self.orders_paused and (
            self.paused_until is None or self.paused_until > (when or timezone.now())
        )

    @classmethod
    def current(cls):
        return cls.objects.get_or_create(pk=1)[0]

    def accepts(self, mode):
        return {"dine_in": self.accepts_dine_in, "takeout": self.accepts_takeout}.get(mode, False)


class BusinessHours(Record):
    """Weekly opening hours. Several rows on one weekday express a lunch break;
    none means closed. Hours past midnight are refused so a day is a calendar day."""

    weekday = models.PositiveSmallIntegerField()  # Monday = 0
    opens_at = models.TimeField()
    closes_at = models.TimeField()

    class Meta:
        ordering = ["weekday", "opens_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(closes_at__gt=models.F("opens_at")),
                name="hours_close_after_open",
            ),
            models.CheckConstraint(condition=models.Q(weekday__lte=6), name="hours_valid_weekday"),
        ]


class Category(Record):
    name = models.CharField(max_length=120, unique=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "created_at"]


class OptionGroup(Record):
    """A question asked about a dish: 甜度, 冰塊, 加料, 大小. One level only.

    Shared by the store and attached to as many dishes as need it, so a tea shop
    writes 甜度 once. Editing a group changes it for every dish that uses it.
    min_select 1 makes it required; max_select 1 makes it a single choice.
    """

    name = models.CharField(max_length=60, unique=True)
    min_select = models.PositiveSmallIntegerField(default=0)
    max_select = models.PositiveSmallIntegerField(default=1)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_select__gte=1)
                & models.Q(max_select__gte=models.F("min_select")),
                name="option_group_select_range",
            )
        ]


class Option(Record):
    group = models.ForeignKey(OptionGroup, on_delete=models.CASCADE, related_name="options")
    name = models.CharField(max_length=60)
    # Added to the dish's price; zero for 半糖, positive for 加珍珠.
    price_delta = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # 珍珠 ran out: the choice stays listed, marked unavailable.
    is_available = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["group", "name"], name="option_name_unique_per_group")
        ]


class MenuItem(Record):
    AVAILABLE, SOLD_OUT = "available", "sold_out"

    # Deleting a category with dishes in it fails rather than taking them along.
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="items")
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(max_length=1000, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Coarse on purpose: no stock count. A race between two customers is settled
    # by the shop when it confirms, not by a counter.
    availability = models.CharField(
        max_length=16,
        choices=[(AVAILABLE, "供應中"), (SOLD_OUT, "已售完")],
        default=AVAILABLE,
    )
    # What the shop would tell staff about selling this, for the Agent only and
    # never shown to customers. The merchant's opinion, not an instruction.
    guidance = models.TextField(max_length=1000, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    # Off the menu entirely, as opposed to on it and sold out today.
    is_active = models.BooleanField(default=True)
    option_groups = models.ManyToManyField(OptionGroup, blank=True, related_name="items")

    class Meta:
        ordering = ["sort_order", "created_at"]

    @property
    def is_orderable(self):
        return self.is_active and self.availability == self.AVAILABLE


class Table(Record):
    """A table, and what a dine-in QR code points at. Everyone at it shares one bill."""

    code = models.CharField(max_length=20, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]


class PickupCounter(models.Model):
    """The day's collection numbers, shared by every entrance. A locked row rather
    than a count, so two orders landing together never take the same number."""

    business_date = models.DateField(primary_key=True)
    last_number = models.PositiveIntegerField(default=0)

    @classmethod
    def take(cls, business_date):
        cls.objects.get_or_create(business_date=business_date)
        counter = cls.objects.select_for_update().get(business_date=business_date)
        counter.last_number += 1
        counter.save(update_fields=["last_number"])
        return counter.last_number


class Tab(Record):
    """The bill. Dine-in: the table is the credential and the tab stays open for
    more rounds. Takeout: one round, a pickup number and a phone to call."""

    DINE_IN, TAKEOUT = "dine_in", "takeout"

    service_mode = models.CharField(max_length=16, choices=[(DINE_IN, "內用"), (TAKEOUT, "外帶")])
    table = models.ForeignKey(
        Table, on_delete=models.PROTECT, null=True, blank=True, related_name="tabs"
    )
    # Staff call this number when something ran out. Never verified: not a credential.
    phone = models.CharField(max_length=20, blank=True)
    # Set when the order came through Agenrena: who to notify and whose orders an
    # Agent may list. Never supplied by the public confirmation request.
    customer = models.ForeignKey(
        CustomerIdentity, on_delete=models.PROTECT, null=True, blank=True, related_name="tabs"
    )
    pickup_code = models.CharField(max_length=8, blank=True)
    # The store's own date, which pickup codes are unique within.
    business_date = models.DateField()
    # Unguessable; the takeout customer's way back to the status page.
    access_token = models.CharField(max_length=64, unique=True, editable=False)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["business_date"])]
        constraints = [
            models.UniqueConstraint(
                fields=["table"],
                condition=models.Q(closed_at__isnull=True, table__isnull=False),
                name="one_open_tab_per_table",
            ),
            models.UniqueConstraint(
                fields=["business_date", "pickup_code"],
                condition=~models.Q(pickup_code=""),
                name="pickup_code_unique_per_day",
            ),
            models.CheckConstraint(
                condition=models.Q(service_mode="dine_in", table__isnull=False)
                | models.Q(service_mode="takeout", table__isnull=True),
                name="tab_table_matches_mode",
            ),
            # Takeout customers walk away; staff need a number to call.
            models.CheckConstraint(
                condition=models.Q(service_mode="dine_in") | ~models.Q(phone=""),
                name="takeout_needs_phone",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.access_token:
            self.access_token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    @property
    def is_open(self):
        return self.closed_at is None

    @property
    def total(self):
        """What is owed: refused, withdrawn and not-yet-confirmed rounds do not count."""
        return sum((r.total for r in self.rounds.all() if r.status in Round.BILLABLE), Decimal("0"))


class Round(Record):
    PENDING, CONFIRMED, COMPLETED = "pending", "confirmed", "completed"
    REJECTED, CANCELLED = "rejected", "cancelled"
    BILLABLE = frozenset({CONFIRMED, COMPLETED})

    tab = models.ForeignKey(Tab, on_delete=models.CASCADE, related_name="rounds")
    status = models.CharField(
        max_length=16,
        choices=[
            (PENDING, "待確認"),
            (CONFIRMED, "製作中"),
            (COMPLETED, "已完成"),
            (REJECTED, "店家未接單"),
            (CANCELLED, "已取消"),
        ],
        default=PENDING,
        db_index=True,
    )
    status_changed_at = models.DateTimeField(default=timezone.now)
    source = models.CharField(
        max_length=16, choices=[("customer", "顧客"), ("agent", "Agent"), ("staff", "店家")]
    )
    customer_note = models.CharField(max_length=200, blank=True)
    # The shop's reason for refusing, written for the customer.
    shop_message = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["created_at", "id"]

    @property
    def total(self):
        return sum((line.total for line in self.items.all()), Decimal("0"))

    def set_status(self, status, *, message=""):
        self.status = status
        self.status_changed_at = timezone.now()
        if message:
            self.shop_message = message
        self.save(update_fields=["status", "status_changed_at", "shop_message"])


class RoundItem(Record):
    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="items")
    # For reporting only; nothing that computes money follows it.
    menu_item = models.ForeignKey(
        MenuItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="order_lines"
    )
    name = models.CharField(max_length=120)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1), name="line_quantity_positive"
            )
        ]

    @property
    def unit_total(self):
        """One of these, with every chosen option's price."""
        return self.unit_price + sum((c.price_delta for c in self.choices.all()), Decimal("0"))

    @property
    def total(self):
        return self.unit_total * self.quantity


class RoundItemChoice(Record):
    """One option chosen on one line, copied the same way as the line: the group
    name too, so "正常" beside "正常" still reads as 甜度 and 冰塊."""

    item = models.ForeignKey(RoundItem, on_delete=models.CASCADE, related_name="choices")
    # For re-sending an amended line; nothing that computes money follows it.
    option = models.ForeignKey(
        Option, on_delete=models.SET_NULL, null=True, blank=True, related_name="order_choices"
    )
    group_name = models.CharField(max_length=60)
    name = models.CharField(max_length=60)
    price_delta = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        ordering = ["created_at", "id"]


class OrderDraft(Record):
    """An Agent-prepared cart that is not an order yet. The raw token appears only
    in the customer's link; the draft becomes an order exactly once."""

    customer = models.ForeignKey(
        CustomerIdentity, on_delete=models.PROTECT, related_name="order_drafts"
    )
    items = models.JSONField()
    customer_note = models.CharField(max_length=200, blank=True)
    token_digest = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField(db_index=True)
    submitted_tab = models.OneToOneField(
        Tab, on_delete=models.PROTECT, null=True, blank=True, related_name="origin_draft"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    @classmethod
    @transaction.atomic
    def issue(cls, **fields):
        token = secrets.token_urlsafe(32)
        return cls.objects.create(token_digest=cls.digest(token), **fields), token

    @property
    def is_expired(self):
        return self.submitted_tab_id is None and self.expires_at <= timezone.now()
