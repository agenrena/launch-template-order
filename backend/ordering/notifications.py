"""What the customer sees in their Agenrena conversation when an order changes.

Only orders that came through Agenrena carry a customer identity; QR orders are
anonymous and are skipped by the core. Staff still phone takeout customers.
"""

import hashlib
import json
from decimal import Decimal

from core.services import notify_customer

from .models import OrderingSettings, Round

PRESENTATION = {
    "placed": ("訂單已送出", "warning"),
    Round.PENDING: ("訂單已送出", "warning"),
    Round.CONFIRMED: ("店家已接單", "success"),
    Round.COMPLETED: ("餐點已完成", "success"),
    Round.REJECTED: ("店家未接單", "cancelled"),
    Round.CANCELLED: ("訂單已取消", "cancelled"),
}


def announce(round_, *, event=""):
    tab = round_.tab
    if tab.customer_id is None:
        return
    if event == "amended":
        header, status = (
            ("訂單已修改，製作中", "success")
            if round_.status == Round.CONFIRMED
            else (
                "訂單已修改",
                "warning",
            )
        )
    else:
        header, status = PRESENTATION[event or round_.status]
    lines = "、".join(describe(line) for line in round_.items.all())
    rows = [
        ("取餐號", tab.pickup_code),
        ("餐點", lines),
        ("金額", money(round_.total, OrderingSettings.current().currency)),
    ]
    if round_.status == Round.REJECTED and round_.shop_message:
        rows.append(("店家說明", round_.shop_message))
    card = {
        "status": status,
        "header": header,
        "content": [
            {"label": label, "value": clip(str(value), 200)} for label, value in rows if value
        ],
    }
    summary = [header, f"取餐號 {tab.pickup_code}" if tab.pickup_code else ""]
    summary.append(round_.shop_message if round_.status == Round.REJECTED else lines)
    notify_customer(
        tab.customer,
        clip(" · ".join(part for part in summary if part), 200),
        card=card,
        message_id=message_id(round_, event, card),
    )


def describe(line):
    options = "、".join(c.name for c in line.choices.all())
    return f"{line.name}{f'（{options}）' if options else ''}×{line.quantity}"


def message_id(round_, event, card):
    """Stable for one state of one order, so a retried request never posts twice;
    different when staff amend the lines without changing the status."""
    material = json.dumps(
        {
            "event": event,
            "status": round_.status,
            "at": round_.status_changed_at.isoformat(),
            "card": card,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(material.encode()).hexdigest()[:16]
    return f"order-{round_.pk}-{event or round_.status}-{digest}"


def money(value, currency):
    value = Decimal(value)
    shown = f"{value:,.0f}" if value == value.to_integral_value() else f"{value:,.2f}"
    return f"{currency} {shown}"


def clip(value, limit):
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"
