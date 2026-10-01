"""Placing and changing orders. The QR page, the Agent and staff are three callers
of these functions, not three implementations of the same idea.

The one rule that differs between them: a customer may not order something the
menu says is sold out; staff may, because they can see the kitchen.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from core.models import CustomerIdentity
from core.permissions import authorize, scoped_customer
from core.services import audit
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from . import hours
from .models import (
    MenuItem,
    OrderDraft,
    OrderingSettings,
    PickupCounter,
    Round,
    RoundItem,
    RoundItemChoice,
    Tab,
    Table,
)
from .notifications import announce

MAX_NOTE = 200
MAX_PHONE = 20
MAX_QUANTITY = 99
MAX_LINES = 50
RECENT_ORDERS = 20


class OrderError(Exception):
    """Refused, with a sentence a person can be told and, when useful, what to do."""

    def __init__(self, code, message, next_steps=""):
        self.code, self.message, self.next_steps = code, message, next_steps
        super().__init__(message)

    @property
    def body(self):
        body = {"error": self.code, "message": self.message}
        if self.next_steps:
            body["next_steps"] = self.next_steps
        return body


@dataclass
class LineSpec:
    item_id: str
    quantity: int = 1
    note: str = ""
    # What staff agreed to charge when it is not the menu price. Never from customers.
    unit_price: Decimal | None = None
    # Chosen option ids, one level: 半糖, 少冰, 加珍珠.
    options: tuple = ()


def parse_lines(raw, *, allow_price=False):
    if not isinstance(raw, list) or not raw:
        raise OrderError("items_required", "請選擇餐點。")
    if len(raw) > MAX_LINES:
        raise OrderError("too_many_lines", f"一次最多 {MAX_LINES} 項餐點。")
    lines = []
    for entry in raw:
        if not isinstance(entry, dict) or not entry.get("item"):
            raise OrderError("bad_item", "請選擇有效餐點。", "每一項都要帶 item（菜單上的 id）。")
        allowed = {"item", "quantity", "note", "options"} | (
            {"unit_price"} if allow_price else set()
        )
        if set(entry) - allowed:
            raise OrderError("bad_item", "餐點包含不支援的欄位。")
        try:
            quantity = int(entry.get("quantity", 1))
        except (TypeError, ValueError):
            raise OrderError("bad_quantity", "請輸入有效數量。") from None
        if not 1 <= quantity <= MAX_QUANTITY:
            raise OrderError("bad_quantity", f"數量需介於 1 到 {MAX_QUANTITY}。")
        note = entry.get("note", "")
        if not isinstance(note, str) or len(note) > MAX_NOTE:
            raise OrderError("bad_note", f"備註最多 {MAX_NOTE} 字。")
        options = entry.get("options", [])
        if (
            not isinstance(options, list)
            or len(options) > 20
            or not all(isinstance(o, str) for o in options)
            or len(set(options)) != len(options)
        ):
            raise OrderError("bad_option", "選項格式錯誤。", "options 是選項 id 的清單，不能重複。")
        lines.append(
            LineSpec(
                item_id=str(entry["item"]),
                quantity=quantity,
                note=note.strip(),
                unit_price=_price(entry.get("unit_price")) if allow_price else None,
                options=tuple(options),
            )
        )
    return lines


def line_payloads(lines):
    return [
        {
            "item": line.item_id,
            "quantity": line.quantity,
            **({"options": list(line.options)} if line.options else {}),
            **({"note": line.note} if line.note else {}),
        }
        for line in lines
    ]


def _price(value):
    if value in (None, ""):
        return None
    try:
        price = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise OrderError("bad_price", "請輸入有效價格。") from None
    if price < 0 or price != price.quantize(Decimal("0.01")) or price >= Decimal("1e8"):
        raise OrderError("bad_price", "價格需為 0 以上、最多兩位小數。")
    return price


def clean_note(value):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > MAX_NOTE:
        raise OrderError("bad_note", f"備註最多 {MAX_NOTE} 字。")
    return value.strip()


def clean_phone(value):
    phone = value.strip() if isinstance(value, str) else ""
    if not phone:
        raise OrderError("phone_required", "請填寫聯絡電話。")
    if len(phone) > MAX_PHONE:
        raise OrderError("bad_phone", f"電話最多 {MAX_PHONE} 字。")
    return phone


def _item(item_id):
    try:
        uuid.UUID(str(item_id))
    except ValueError:
        raise OrderError("item_not_found", "菜單上沒有這道菜。") from None
    item = (
        MenuItem.objects.filter(pk=item_id, is_active=True)
        .select_related("category")
        .prefetch_related("option_groups__options")
        .first()
    )
    if item is None:
        raise OrderError("item_not_found", "菜單上沒有這道菜。")
    return item


def _instead_of(item, limit=4):
    """What else the same part of the menu has, for a refusal to offer."""
    others = list(
        MenuItem.objects.filter(
            category=item.category, is_active=True, availability=MenuItem.AVAILABLE
        )
        .exclude(pk=item.pk)
        .values_list("name", flat=True)[:limit]
    )
    return f"同一類還有：{'、'.join(others)}。" if others else ""


def _choices(item, option_ids, *, enforce_availability):
    """Check the chosen options against the questions this dish asks. Required
    or optional, one or several: min_select and max_select decide all of it."""
    wanted = set(option_ids)
    chosen = []
    for group in item.option_groups.all():
        picked = [o for o in group.options.all() if str(o.pk) in wanted]
        available = "、".join(o.name for o in group.options.all() if o.is_available)
        hint = f"「{group.name}」可以選：{available}。" if available else ""
        if len(picked) < group.min_select:
            raise OrderError(
                "option_required",
                f"{item.name}的「{group.name}」要選 {group.min_select} 個。",
                hint,
            )
        if len(picked) > group.max_select:
            raise OrderError(
                "too_many_options", f"{item.name}的「{group.name}」最多選 {group.max_select} 個。"
            )
        for option in picked:
            if enforce_availability and not option.is_available:
                raise OrderError("option_unavailable", f"{option.name}暫無供應。", hint)
            wanted.discard(str(option.pk))
            chosen.append((group, option))
    if wanted:
        # An option from a question this dish does not ask. Refused rather than
        # dropped: silently dropping a choice charges for something not given.
        raise OrderError("option_not_offered", f"{item.name}沒有這個選項。")
    return chosen


def validate_lines(lines):
    """Customer rules, without writing anything."""
    for spec in lines:
        item = _item(spec.item_id)
        if not item.is_orderable:
            raise OrderError("item_unavailable", f"{item.name}暫無供應。", _instead_of(item))
        _choices(item, spec.options, enforce_availability=True)


def _write_lines(round_, lines, *, enforce_availability):
    for spec in lines:
        item = _item(spec.item_id)
        if enforce_availability and not item.is_orderable:
            raise OrderError("item_unavailable", f"{item.name}暫無供應。", _instead_of(item))
        chosen = _choices(item, spec.options, enforce_availability=enforce_availability)
        line = RoundItem.objects.create(
            round=round_,
            menu_item=item,
            name=item.name,
            unit_price=item.price if spec.unit_price is None else spec.unit_price,
            quantity=spec.quantity,
            note=spec.note,
        )
        RoundItemChoice.objects.bulk_create(
            RoundItemChoice(
                item=line,
                option=option,
                group_name=group.name,
                name=option.name,
                price_delta=option.price_delta,
            )
            for group, option in chosen
        )


def require_accepting(mode):
    if not OrderingSettings.current().accepts(mode):
        word = "內用" if mode == Tab.DINE_IN else "外帶"
        raise OrderError("mode_not_offered", f"這家店沒有提供{word}。")
    accepting, reason = hours.accepting_orders()
    if not accepting:
        raise OrderError("not_accepting_orders", reason, "請轉達停止接單的原因。")


# ---- Public QR ordering ----


def join_table(code):
    """Sitting down: the table's open bill, or a new one. The table is the credential."""
    require_accepting(Tab.DINE_IN)
    table = Table.objects.filter(code=str(code or "").strip(), is_active=True).first()
    if table is None:
        raise OrderError("table_not_found", "找不到桌號，請重新掃碼。")
    tab = Tab.objects.filter(table=table, closed_at__isnull=True).first()
    if tab is not None:
        return tab
    try:
        with transaction.atomic():
            return Tab.objects.create(
                service_mode=Tab.DINE_IN, table=table, business_date=hours.business_date()
            )
    except IntegrityError:
        # Two people at the same table scanned together; both join the same bill.
        return Tab.objects.get(table=table, closed_at__isnull=True)


@transaction.atomic
def place_round(tab, lines, *, note=""):
    """Dine-in: another batch onto the table's open bill."""
    tab = Tab.objects.select_for_update().get(pk=tab.pk)
    if tab.service_mode != Tab.DINE_IN:
        raise OrderError("takeout_already_sent", "外帶訂單已送出，無法加點。")
    if not tab.is_open:
        raise OrderError("tab_closed", "已關帳，無法加點。")
    require_accepting(Tab.DINE_IN)
    round_ = Round.objects.create(tab=tab, source="customer", customer_note=note)
    _write_lines(round_, lines, enforce_availability=True)
    return round_


@transaction.atomic
def place_takeout(lines, *, phone, note="", source="customer", customer=None):
    """The bill, the pickup number and the food together: a number is taken only
    when there is food under it."""
    require_accepting(Tab.TAKEOUT)
    today = hours.business_date()
    tab = Tab.objects.create(
        service_mode=Tab.TAKEOUT,
        phone=phone,
        customer=customer,
        business_date=today,
        pickup_code=str(PickupCounter.take(today)),
    )
    round_ = Round.objects.create(tab=tab, source=source, customer_note=note)
    _write_lines(round_, lines, enforce_availability=True)
    return tab


# ---- Staff ----

TRANSITIONS = {
    Round.PENDING: {Round.CONFIRMED, Round.REJECTED, Round.CANCELLED},
    Round.CONFIRMED: {Round.REJECTED, Round.COMPLETED},
    Round.COMPLETED: set(),
    Round.REJECTED: set(),
    Round.CANCELLED: set(),
}
EVENTS = {
    Round.CONFIRMED: "order.confirmed",
    Round.REJECTED: "order.rejected",
    Round.COMPLETED: "order.completed",
    Round.CANCELLED: "order.cancelled",
}


def _locked(round_):
    # Lock only the round: PostgreSQL cannot lock the nullable side of a join.
    return (
        Round.objects.select_for_update(of=("self",))
        .select_related("tab__customer")
        .get(pk=round_.pk)
    )


def _transition(actor, round_, status, *, message=""):
    round_ = _locked(round_)
    if status not in TRANSITIONS[round_.status]:
        raise OrderError("bad_transition", "目前狀態無法執行此操作，請更新訂單。")
    round_.set_status(status, message=message)
    audit(actor, EVENTS[status], round_, customer=round_.tab.customer)
    announce(round_)
    return round_


@transaction.atomic
def confirm_round(actor, round_):
    authorize(actor, "orders.manage")
    return _transition(actor, round_, Round.CONFIRMED)


@transaction.atomic
def reject_round(actor, round_, message=""):
    authorize(actor, "orders.manage")
    if not isinstance(message, str) or len(message) > 500:
        raise OrderError("bad_message", "說明最多 500 字。")
    return _transition(actor, round_, Round.REJECTED, message=message.strip())


@transaction.atomic
def complete_round(actor, round_):
    authorize(actor, "orders.manage")
    return _transition(actor, round_, Round.COMPLETED)


@transaction.atomic
def amend_round(actor, round_, lines, *, confirm=False):
    """Rewrite a round as what was agreed with the customer. Staff rules: sold-out
    flags do not block, and the status stays unless `confirm` accepts it too."""
    authorize(actor, "orders.manage")
    round_ = _locked(round_)
    if round_.status not in (Round.PENDING, Round.CONFIRMED):
        raise OrderError("round_closed", "餐點已結束，無法修改。")
    round_.items.all().delete()
    _write_lines(round_, lines, enforce_availability=False)
    audit(actor, "order.amended", round_, customer=round_.tab.customer)
    if confirm and round_.status == Round.PENDING:
        round_.set_status(Round.CONFIRMED)
        audit(actor, "order.confirmed", round_, customer=round_.tab.customer)
        announce(round_)
    else:
        announce(round_, event="amended")
    return round_


@transaction.atomic
def close_tab(actor, tab):
    """Settled at the counter. Stops more rounds; does not complete food or take money."""
    authorize(actor, "orders.manage")
    tab = Tab.objects.select_for_update().get(pk=tab.pk)
    if tab.closed_at is None:
        tab.closed_at = timezone.now()
        tab.save(update_fields=["closed_at"])
        audit(actor, "order.tab_closed", tab, customer=tab.customer)
    return tab


# ---- Agent ----


def _customer_for_draft(actor, customer_ref, customer_name):
    ref, identity = scoped_customer(actor, "order.create", customer_ref)
    name = customer_name.strip() if isinstance(customer_name, str) else ""
    if customer_name not in (None, "") and not isinstance(customer_name, str):
        raise OrderError("invalid_customer_name", "稱呼格式不正確。")
    if len(name) > 40:
        raise OrderError("invalid_customer_name", "稱呼最多 40 字。")
    if identity is None or not identity.display_name:
        if not name:
            raise OrderError(
                "new_customer_name_required",
                "新客必填名稱。",
                "先問顧客怎麼稱呼，再帶 customer_name 重新建立連結。",
            )
    identity, _ = CustomerIdentity.objects.get_or_create(agenrena_customer_ref=ref)
    identity = CustomerIdentity.objects.select_for_update().get(pk=identity.pk)
    if name and name != identity.display_name:
        identity.display_name = name
        identity.save(update_fields=["display_name"])
    return identity


@transaction.atomic
def create_draft(actor, *, customer_ref, items, customer_name=None, note=None):
    """Prepare a cart for the customer to confirm. No order, pickup number or
    kitchen ticket exists until they press confirm on the link."""
    authorize(actor, "order.create", scope="customer", customer_ref=customer_ref)
    lines = parse_lines(items)
    note = clean_note(note)
    require_accepting(Tab.TAKEOUT)
    validate_lines(lines)
    # After the cart is checked, so a refused cart does not throw away a new name.
    customer = _customer_for_draft(actor, customer_ref, customer_name)
    draft, token = OrderDraft.issue(
        customer=customer,
        items=line_payloads(lines),
        customer_note=note,
        expires_at=timezone.now() + timedelta(minutes=settings.ORDER_DRAFT_TTL_MINUTES),
    )
    audit(actor, "order.draft_created", draft, customer=customer)
    return draft, token


def draft_for(token, *, lock=False):
    rows = OrderDraft.objects.select_related("customer", "submitted_tab")
    if lock:
        rows = OrderDraft.objects.select_for_update(of=("self",))
    return rows.filter(token_digest=OrderDraft.digest(str(token))).first()


@transaction.atomic
def confirm_draft(token, *, phone, items=None, note=None):
    """The customer confirms on the link. Idempotent: a double tap gets the same order."""
    draft = draft_for(token, lock=True)
    if draft is None:
        raise OrderError("not_found", "找不到這個連結。")
    if draft.submitted_tab_id:
        return draft.submitted_tab, False
    if draft.expires_at <= timezone.now():
        raise OrderError("draft_expired", "確認連結已過期。", "請回原對話取得新連結。")
    lines = parse_lines(draft.items if items is None else items)
    note = clean_note(draft.customer_note if note is None else note)
    tab = place_takeout(
        lines,
        phone=clean_phone(phone),
        note=note,
        source="agent",
        customer=CustomerIdentity.objects.get(pk=draft.customer_id),
    )
    draft.items = line_payloads(lines)
    draft.customer_note = note
    draft.submitted_tab = tab
    draft.submitted_at = timezone.now()
    draft.save(update_fields=["items", "customer_note", "submitted_tab", "submitted_at"])
    announce(tab.rounds.get(), event="placed")
    return tab, True


def customer_orders(actor, permission, customer_ref):
    """This customer's orders, newest first. Another customer's are not found."""
    _, identity = scoped_customer(actor, permission, customer_ref)
    rows = Tab.objects.prefetch_related("rounds__items__choices")
    return rows.filter(customer=identity) if identity else rows.none()


@transaction.atomic
def cancel_by_customer(actor, *, customer_ref, order_id):
    """Only before the shop has agreed to make it; after that, talk to the shop."""
    tab = customer_orders(actor, "order.cancel", customer_ref).filter(pk=order_id).first()
    if tab is None:
        raise OrderError("not_found", "找不到這筆訂單。")
    round_ = _locked(tab.rounds.first())
    if round_.status == Round.CANCELLED:
        return tab
    if round_.status == Round.CONFIRMED:
        raise OrderError("already_confirmed", "店家已接單，無法直接取消。", "請聯絡店家。")
    if Round.CANCELLED not in TRANSITIONS[round_.status]:
        raise OrderError("bad_transition", "這筆訂單已結束，無法取消。")
    round_.set_status(Round.CANCELLED)
    tab = Tab.objects.select_for_update().get(pk=tab.pk)
    tab.closed_at = tab.closed_at or timezone.now()
    tab.save(update_fields=["closed_at"])
    audit(actor, "order.cancelled", round_, customer=tab.customer)
    announce(round_)
    return tab


# ---- Menu, tables, hours and settings (console) ----


def save_catalog(actor, serializer):
    from .photos import delete_files

    authorize(actor, "menu.write")
    serializer.photo_writes = []
    try:
        with transaction.atomic():
            # Serialize edits to the same dish, including its ordered photo set.
            if isinstance(serializer.instance, MenuItem):
                serializer.instance = MenuItem.objects.select_for_update().get(
                    pk=serializer.instance.pk
                )
            new = serializer.instance is None
            result = serializer.save()
            name = result._meta.model_name
            audit(
                actor,
                f"{name}.created" if new else f"{name}.updated",
                result,
                detail={"fields": sorted(serializer.validated_data)},
            )
            return result
    except Exception:
        delete_files(serializer.photo_writes)
        raise


@transaction.atomic
def save_settings(actor, serializer):
    authorize(actor, "ordering.settings")
    result = serializer.save()
    audit(actor, "ordering.settings_updated", detail={"fields": sorted(serializer.validated_data)})
    return result


@transaction.atomic
def replace_hours(actor, weekly):
    """All seven days at once, so a failed check never leaves half a week."""
    from .models import BusinessHours

    authorize(actor, "ordering.settings")
    if not isinstance(weekly, list) or sorted(
        d.get("weekday") for d in weekly if isinstance(d, dict)
    ) != list(range(7)):
        raise ValidationError("請提供週一到週日共七天的營業時間。")
    rows = []
    for day in weekly:
        intervals = day.get("intervals")
        if not isinstance(intervals, list) or len(intervals) > 8:
            raise ValidationError("每天最多八個時段。")
        parsed = []
        for interval in intervals:
            try:
                opens = timezone.datetime.strptime(interval["opens_at"], "%H:%M").time()
                closes = timezone.datetime.strptime(interval["closes_at"], "%H:%M").time()
            except (KeyError, TypeError, ValueError):
                raise ValidationError("時間格式為 HH:MM。") from None
            if closes <= opens:
                raise ValidationError("結束時間必須晚於開始時間，不能跨日。")
            parsed.append((opens, closes))
        parsed.sort()
        for (_, end), (start, _) in zip(parsed, parsed[1:]):
            if start < end:
                raise ValidationError("同一天的時段不能重疊。")
        rows += [BusinessHours(weekday=day["weekday"], opens_at=o, closes_at=c) for o, c in parsed]
    BusinessHours.objects.all().delete()
    BusinessHours.objects.bulk_create(rows)
    audit(actor, "ordering.hours_updated")
    return hours.weekly()


@transaction.atomic
def pause_ordering(actor, *, minutes=None, reason=""):
    """Stop new orders everywhere for a while, or until resumed."""
    authorize(actor, "orders.manage")
    if minutes not in (None, 15, 30, 60):
        raise ValidationError({"minutes": "請選擇 15、30、60 分鐘，或直到手動恢復。"})
    if not isinstance(reason, str) or len(reason) > 120:
        raise ValidationError({"reason": "原因最多 120 字。"})
    row = OrderingSettings.objects.select_for_update().get(pk=1)
    row.orders_paused = True
    row.paused_until = timezone.now() + timedelta(minutes=minutes) if minutes else None
    row.pause_reason = reason.strip()
    row.save(update_fields=["orders_paused", "paused_until", "pause_reason"])
    audit(actor, "ordering.paused", detail={"minutes": minutes})
    return hours.status()


@transaction.atomic
def resume_ordering(actor):
    authorize(actor, "orders.manage")
    OrderingSettings.objects.filter(pk=1).update(
        orders_paused=False, paused_until=None, pause_reason=""
    )
    audit(actor, "ordering.resumed")
    return hours.status()


def today_summary(actor):
    """Today's service in two numbers: billed orders and what they came to. Pending,
    refused and withdrawn rounds do not count; this is not money taken."""
    authorize(actor, "orders.read")
    today = hours.business_date()
    rounds = Round.objects.filter(tab__business_date=today).prefetch_related("items__choices")
    billed = [r for r in rounds if r.status in Round.BILLABLE]
    return {
        "business_date": today,
        "orders": len({r.tab_id for r in billed}),
        "revenue": f"{sum((r.total for r in billed), Decimal('0')):.2f}",
        "pending": sum(1 for r in rounds if r.status == Round.PENDING),
        "currency": OrderingSettings.current().currency,
    }
