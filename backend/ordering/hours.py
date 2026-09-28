"""Whether the store is taking orders right now.

Every entrance asks this and gets the same answer, with a sentence: each caller
has to tell somebody, and "closed" without "we open again at five" makes people
phone up.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.models import Business
from django.utils import timezone

from .models import BusinessHours, OrderingSettings

WEEKDAYS = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]


def zone():
    return ZoneInfo(Business.current().timezone)


def business_date(when=None):
    """The store's own date, which pickup numbers are unique within."""
    return (when or timezone.now()).astimezone(zone()).date()


def accepting_orders(when=None):
    settings = OrderingSettings.current()
    when = when or timezone.now()
    local = when.astimezone(zone())
    if settings.is_paused(when):
        reason = settings.pause_reason or "店家忙碌中"
        until = settings.paused_until
        return False, (
            f"暫停接單：{reason}。"
            + (f"預計 {until.astimezone(zone()):%H:%M} 恢復。" if until else "請稍後再試。")
        )
    rows = BusinessHours.objects.filter(weekday=local.weekday())
    if not rows:
        return False, "今天沒有營業。"
    now = local.replace(tzinfo=None)
    later = []
    for row in rows:
        opens = datetime.combine(local.date(), row.opens_at)
        # The kitchen stops before the door does.
        last_order = datetime.combine(local.date(), row.closes_at) - timedelta(
            minutes=settings.last_order_minutes_before_close
        )
        if opens <= now < last_order:
            return True, ""
        if now < opens:
            later.append(opens)
    if later:
        return False, f"還沒開始接單，{min(later):%H:%M} 開始。"
    return False, "今天已經停止接單了。"


def weekly():
    days = [{"weekday": day, "label": WEEKDAYS[day], "intervals": []} for day in range(7)]
    for row in BusinessHours.objects.all():
        days[row.weekday]["intervals"].append(
            {"opens_at": f"{row.opens_at:%H:%M}", "closes_at": f"{row.closes_at:%H:%M}"}
        )
    return days


def status():
    accepting, reason = accepting_orders()
    settings = OrderingSettings.current()
    paused = settings.is_paused()
    return {
        "accepting_orders": accepting,
        "closed_reason": reason,
        "paused": paused,
        "paused_until": settings.paused_until if paused else None,
        "pause_reason": settings.pause_reason if paused else "",
        "weekly_hours": weekly(),
        "last_order_minutes_before_close": settings.last_order_minutes_before_close,
    }
