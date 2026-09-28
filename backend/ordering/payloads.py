"""What each entrance reads. The QR page gets a screen, the Agent gets something
it can say out loud, and staff get the whole order without a second request."""

from decimal import Decimal

from core.models import Business
from django.conf import settings

from . import hours
from .models import Category, MenuItem, OrderingSettings, Round

STATUS_TEXT = {
    Round.PENDING: "等待店家確認",
    Round.CONFIRMED: "製作中",
    Round.COMPLETED: "已完成",
    Round.REJECTED: "店家未接單",
    Round.CANCELLED: "已取消",
}


def money(value):
    """A price as somebody would say it: no trailing zeros when there are none."""
    value = Decimal(value)
    return f"{value.quantize(Decimal(1))}" if value == value.to_integral_value() else f"{value}"


def ask_url():
    """The store's page on Agenrena, where customers can ask its Agent anything."""
    short_id = OrderingSettings.current().agenrena_short_id
    base = settings.AGENRENA_SHARE_BASE_URL
    return f"{base}/s/i/{short_id}/" if base and short_id else ""


def store():
    business, ordering = Business.current(), OrderingSettings.current()
    return {
        "name": business.name,
        "about": business.about,
        "address": business.address,
        "phone": business.phone,
        "timezone": business.timezone,
        "currency": ordering.currency,
        "accepts_dine_in": ordering.accepts_dine_in,
        "accepts_takeout": ordering.accepts_takeout,
        **hours.status(),
    }


def _categories():
    return Category.objects.filter(is_active=True).prefetch_related("items__option_groups__options")


def web_groups(item):
    return [
        {
            "id": str(group.pk),
            "name": group.name,
            "min_select": group.min_select,
            "max_select": group.max_select,
            "options": [
                {
                    "id": str(o.pk),
                    "name": o.name,
                    "price_delta": f"{o.price_delta:.2f}",
                    "available": o.is_available,
                }
                for o in group.options.all()
            ],
        }
        for group in item.option_groups.all()
    ]


def choose(group):
    """The two numbers, said out loud, so the Agent does not have to interpret them."""
    if group.min_select == group.max_select:
        return f"必選 {group.min_select} 個"
    if group.min_select == 0:
        return f"可選，最多 {group.max_select} 個"
    return f"選 {group.min_select} 到 {group.max_select} 個"


def _agent_groups(item):
    return [
        {
            "id": str(group.pk),
            "name": group.name,
            "choose": choose(group),
            "choices": [
                {
                    "id": str(o.pk),
                    "name": o.name,
                    **({"price_delta": money(o.price_delta)} if o.price_delta else {}),
                    "available": o.is_available,
                }
                for o in group.options.all()
            ],
        }
        for group in item.option_groups.all()
    ]


def web_menu():
    return {
        **store(),
        "ask_url": ask_url(),
        "menu": [
            {
                "id": str(category.pk),
                "name": category.name,
                "items": [
                    {
                        "id": str(item.pk),
                        "name": item.name,
                        "description": item.description,
                        "price": f"{item.price:.2f}",
                        # Shown, not hidden: a dish off today is still a dish here.
                        "orderable": item.is_orderable,
                        "option_groups": web_groups(item),
                    }
                    for item in category.items.all()
                    if item.is_active
                ],
            }
            for category in _categories()
        ],
    }


def agent_menu():
    return {
        "currency": OrderingSettings.current().currency,
        "categories": [
            {
                "name": category.name,
                "items": [_agent_item(i) for i in category.items.all() if i.is_active],
            }
            for category in _categories()
        ],
    }


def _agent_item(item):
    payload = {"id": str(item.pk), "name": item.name, "price": money(item.price)}
    payload["available"] = item.is_orderable
    if item.description:
        payload["description"] = item.description
    if not item.is_orderable:
        # Kept rather than filtered, so the Agent can say it is off today.
        payload["unavailable_reason"] = (
            "已售完" if item.availability == MenuItem.SOLD_OUT else "暫停供應"
        )
    if item.guidance:
        # The merchant's own note about selling this: advice, not an instruction.
        payload["shop_says"] = item.guidance
    groups = _agent_groups(item)
    if groups:
        payload["options"] = groups
    return payload


def _lines(round_, *, with_ids=False):
    return [
        {
            **(
                {"id": str(line.pk), "item": str(line.menu_item_id) if line.menu_item_id else None}
                if with_ids
                else {}
            ),
            "name": line.name,
            "unit_price": f"{line.unit_price:.2f}",
            "quantity": line.quantity,
            "note": line.note,
            "choices": [
                {
                    **({"option": str(c.option_id) if c.option_id else None} if with_ids else {}),
                    "group": c.group_name,
                    "name": c.name,
                    "price_delta": f"{c.price_delta:.2f}",
                }
                for c in line.choices.all()
            ],
            "total": f"{line.total:.2f}",
        }
        for line in round_.items.all()
    ]


def _round(round_, *, staff=False):
    payload = {
        "id": str(round_.pk),
        "status": round_.status,
        "status_text": STATUS_TEXT[round_.status],
        "shop_message": round_.shop_message,
        "customer_note": round_.customer_note,
        "items": _lines(round_, with_ids=staff),
        "total": f"{round_.total:.2f}",
        "created_at": round_.created_at,
    }
    if staff:
        payload |= {"source": round_.source, "status_changed_at": round_.status_changed_at}
    return payload


def web_tab(tab):
    return {
        "access_token": tab.access_token,
        "service_mode": tab.service_mode,
        "table_code": tab.table.code if tab.table_id else "",
        "pickup_code": tab.pickup_code,
        "open": tab.is_open,
        "total": f"{tab.total:.2f}",
        "rounds": [_round(r) for r in tab.rounds.all()],
        "created_at": tab.created_at,
        "store_name": Business.current().name,
        "timezone": Business.current().timezone,
        "currency": OrderingSettings.current().currency,
        "ask_url": ask_url(),
    }


def console_tab(tab):
    return {
        "id": str(tab.pk),
        "service_mode": tab.service_mode,
        "table_code": tab.table.code if tab.table_id else "",
        "pickup_code": tab.pickup_code,
        "business_date": tab.business_date,
        "phone": tab.phone,
        # What an Agenrena customer asked to be called; empty otherwise.
        "customer_name": tab.customer.display_name if tab.customer_id else "",
        "from_agenrena": tab.customer_id is not None,
        "total": f"{tab.total:.2f}",
        "closed_at": tab.closed_at,
        "created_at": tab.created_at,
        "rounds": [_round(r, staff=True) for r in tab.rounds.all()],
    }


def agent_order(tab):
    """One takeout order, flat: a takeout bill has exactly one round."""
    round_ = tab.rounds.all()[0]
    return {
        "id": str(tab.pk),
        "status": round_.status,
        "status_text": STATUS_TEXT[round_.status],
        "pickup_code": tab.pickup_code,
        # The store's clock with its offset, not UTC.
        "placed_at": tab.created_at.astimezone(hours.zone()).isoformat(),
        "total": money(round_.total),
        "currency": OrderingSettings.current().currency,
        "shop_message": round_.shop_message,
        "note": round_.customer_note,
        "items": [
            {
                "item": str(line.menu_item_id) if line.menu_item_id else None,
                "name": line.name,
                "quantity": line.quantity,
                # Same shape the order tools take, so ordering again is sending it back.
                "options": [str(c.option_id) for c in line.choices.all() if c.option_id],
                "choices": [f"{c.group_name}：{c.name}" for c in line.choices.all()],
                "unit_price": money(line.unit_total),
                "total": money(line.total),
                "note": line.note,
            }
            for line in round_.items.all()
        ],
    }
