from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from core.models import (
    AgenrenaConnection,
    AgentKey,
    AgentRole,
    AuditEvent,
    CustomerIdentity,
    Membership,
)
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from ordering import hours
from ordering.models import (
    BusinessHours,
    Category,
    MenuItem,
    OrderDraft,
    OrderingSettings,
    PickupCounter,
    Round,
    Tab,
    Table,
)
from ordering.services import parse_lines, place_takeout

REF_A, REF_B, REF_NEW = (f"bcr_{n:032x}" for n in (0xA, 0xB, 0x1))
PASSWORD = "Testing-private-password-739!"


def open_all_day():
    BusinessHours.objects.all().delete()
    for weekday in range(7):
        BusinessHours.objects.create(weekday=weekday, opens_at=time(0), closes_at=time(23, 59, 59))


def menu(obj):
    obj.mains = Category.objects.create(name="主餐", sort_order=1)
    obj.drinks = Category.objects.create(name="飲料", sort_order=2)
    obj.burger = MenuItem.objects.create(category=obj.mains, name="牛肉堡", price=120)
    obj.chicken = MenuItem.objects.create(category=obj.mains, name="雞腿堡", price=110)
    obj.tea = MenuItem.objects.create(category=obj.drinks, name="紅茶", price=30)
    obj.table = Table.objects.create(code="A1")
    open_all_day()


class OrderingTests(TestCase):
    def setUp(self):
        menu(self)
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", password=PASSWORD)
        Membership.objects.create(user=self.owner, role="owner")
        self.admin = User.objects.create_user(username="manager", password=PASSWORD)
        Membership.objects.create(user=self.admin, role="admin")
        self.console = APIClient()
        self.console.force_login(self.admin)
        self.web = APIClient()
        _, secret = AgentKey.issue("Store Agent", AgentRole.objects.get(pk="customer_service"))
        self.agent = APIClient()
        self.agent.credentials(HTTP_AUTHORIZATION="Bearer " + secret)
        cache.clear()  # throttles

    def takeout(self, items=None, phone="0912345678", **extra):
        return self.web.post(
            "/api/web/orders/",
            {
                "phone": phone,
                "items": [{"item": str(self.burger.pk)}] if items is None else items,
                **extra,
            },
            format="json",
        )

    def draft(self, ref=REF_A, **extra):
        body = {"customer_ref": ref, "items": [{"item": str(self.burger.pk), "quantity": 2}]}
        return self.agent.post("/api/agent-api/order-drafts/", {**body, **extra}, format="json")

    def token(self, response):
        return response.data["confirmation_url"].rsplit("/d/", 1)[1]

    def action(self, round_id, action, data=None):
        return self.console.post(
            f"/api/console/rounds/{round_id}/{action}/", data or {}, format="json"
        )

    # ---- Public QR ordering ----

    def test_public_menu_marks_sold_out_and_hides_off_menu_dishes(self):
        self.chicken.availability = MenuItem.SOLD_OUT
        self.chicken.save()
        MenuItem.objects.create(category=self.mains, name="季節限定", price=90, is_active=False)
        data = self.web.get("/api/web/store/").json()
        self.assertTrue(data["accepting_orders"])
        mains = data["menu"][0]
        self.assertEqual([i["name"] for i in mains["items"]], ["牛肉堡", "雞腿堡"])
        self.assertFalse(mains["items"][1]["orderable"])
        self.assertNotIn("guidance", str(data))

    def test_takeout_needs_phone_takes_pickup_numbers_and_snapshots_price(self):
        refused = self.takeout(phone="")
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.data["error"], "phone_required")
        first = self.takeout(
            items=[{"item": str(self.burger.pk), "quantity": 2, "note": "不要洋蔥"}]
        )
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data["pickup_code"], "1")
        self.assertEqual(first.data["rounds"][0]["status"], "pending")
        self.burger.price = 150
        self.burger.save()
        status = self.web.get(f"/api/web/tabs/{first.data['access_token']}/").data
        line = status["rounds"][0]["items"][0]
        self.assertEqual(
            (line["unit_price"], line["total"], line["note"]), ("120.00", "240.00", "不要洋蔥")
        )
        # Not billable until the shop confirms.
        self.assertEqual(status["total"], "0.00")
        self.assertEqual(self.takeout().data["pickup_code"], "2")

    def test_sold_out_is_refused_with_what_else_the_category_has(self):
        self.burger.availability = MenuItem.SOLD_OUT
        self.burger.save()
        r = self.takeout()
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["error"], "item_unavailable")
        self.assertIn("雞腿堡", r.data["next_steps"])
        self.assertEqual(Tab.objects.count(), 0)
        self.assertEqual(PickupCounter.objects.first(), None)

    def test_bad_lines_are_refused(self):
        for items in [
            [],
            [{"item": "not-a-uuid"}],
            [{"item": str(self.burger.pk), "quantity": 0}],
            [{"item": str(self.burger.pk), "unit_price": "1"}],
        ]:
            self.assertEqual(self.takeout(items=items).status_code, 409, items)
        self.assertEqual(Tab.objects.count(), 0)

    def test_dine_in_table_shares_one_bill_until_closed(self):
        one = self.web.post("/api/web/tabs/", {"table": "A1"}, format="json")
        two = self.web.post("/api/web/tabs/", {"table": "A1"}, format="json")
        self.assertEqual(one.data["access_token"], two.data["access_token"])
        self.assertEqual(one.data["table_code"], "A1")
        token = one.data["access_token"]
        for item in [self.burger, self.tea]:
            r = self.web.post(
                f"/api/web/tabs/{token}/rounds/", {"items": [{"item": str(item.pk)}]}, format="json"
            )
            self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(r.data["rounds"]), 2)
        self.assertEqual(
            self.web.post("/api/web/tabs/", {"table": "Z9"}, format="json").status_code, 409
        )
        tab = Tab.objects.get(access_token=token)
        self.console.post(f"/api/console/tabs/{tab.pk}/close/", {}, format="json")
        refused = self.web.post(
            f"/api/web/tabs/{token}/rounds/", {"items": [{"item": str(self.tea.pk)}]}, format="json"
        )
        self.assertEqual(refused.data["error"], "tab_closed")
        again = self.web.post("/api/web/tabs/", {"table": "A1"}, format="json")
        self.assertNotEqual(again.data["access_token"], token)

    def test_takeout_bill_takes_no_second_round(self):
        token = self.takeout().data["access_token"]
        r = self.web.post(
            f"/api/web/tabs/{token}/rounds/", {"items": [{"item": str(self.tea.pk)}]}, format="json"
        )
        self.assertEqual(r.data["error"], "takeout_already_sent")

    def test_modes_and_hours_close_every_entrance(self):
        settings = OrderingSettings.current()
        settings.accepts_takeout = False
        settings.save()
        self.assertEqual(self.takeout().data["error"], "mode_not_offered")
        self.assertEqual(self.draft(customer_name="Ada").data["error"], "mode_not_offered")
        settings.accepts_takeout = True
        settings.save()
        BusinessHours.objects.all().delete()
        for response in [
            self.takeout(),
            self.web.post("/api/web/tabs/", {"table": "A1"}, format="json"),
            self.draft(customer_name="Ada"),
        ]:
            self.assertEqual(response.data["error"], "not_accepting_orders")
            self.assertEqual(response.data["message"], "今天沒有營業。")

    def test_opening_time_and_last_order(self):
        BusinessHours.objects.all().delete()
        zone = ZoneInfo("Asia/Taipei")
        day = date(2030, 1, 7)  # Monday
        BusinessHours.objects.create(weekday=0, opens_at=time(11), closes_at=time(14))
        BusinessHours.objects.create(weekday=0, opens_at=time(17), closes_at=time(21))
        settings = OrderingSettings.current()
        settings.last_order_minutes_before_close = 30
        settings.save()

        def at(h, m=0):
            return hours.accepting_orders(datetime(2030, 1, 7, h, m, tzinfo=zone))

        self.assertEqual(at(10), (False, "還沒開始接單，11:00 開始。"))
        self.assertEqual(at(12), (True, ""))
        self.assertEqual(at(13, 40), (False, "還沒開始接單，17:00 開始。"))
        self.assertEqual(at(20, 29)[0], True)
        self.assertEqual(at(20, 30), (False, "今天已經停止接單了。"))
        self.assertEqual(
            hours.accepting_orders(datetime.combine(day + timedelta(days=1), time(12), zone))[1],
            "今天沒有營業。",
        )

    def test_pickup_numbers_restart_each_business_day(self):
        self.assertEqual([PickupCounter.take(date(2030, 1, 1)) for _ in range(3)], [1, 2, 3])
        self.assertEqual(PickupCounter.take(date(2030, 1, 2)), 1)

    # ---- Console ----

    def test_staff_confirm_complete_and_bill(self):
        token = self.takeout().data["access_token"]
        round_ = Tab.objects.get(access_token=token).rounds.get()
        self.assertEqual(self.action(round_.pk, "complete").data["error"], "bad_transition")
        tab = self.action(round_.pk, "confirm").data
        self.assertEqual((tab["rounds"][0]["status"], tab["total"]), ("confirmed", "120.00"))
        self.assertEqual(
            self.action(round_.pk, "complete").data["rounds"][0]["status"], "completed"
        )
        self.assertEqual(self.action(round_.pk, "reject").data["error"], "bad_transition")
        self.assertEqual(self.action(round_.pk, "dance").data["error"], "unknown_action")
        self.assertTrue(AuditEvent.objects.filter(action="order.completed").exists())

    def test_staff_amend_ignores_sold_out_keeps_status_and_can_confirm(self):
        token = self.takeout().data["access_token"]
        round_ = Tab.objects.get(access_token=token).rounds.get()
        self.chicken.availability = MenuItem.SOLD_OUT
        self.chicken.save()
        # Agreed on the phone: a chicken burger for the same price.
        items = [{"item": str(self.chicken.pk), "unit_price": "120"}, {"item": str(self.tea.pk)}]
        tab = self.action(round_.pk, "amend", {"items": items}).data
        self.assertEqual(tab["rounds"][0]["status"], "pending")
        self.assertEqual(
            [(i["name"], i["unit_price"]) for i in tab["rounds"][0]["items"]],
            [("雞腿堡", "120.00"), ("紅茶", "30.00")],
        )
        tab = self.action(round_.pk, "amend", {"items": items[:1], "confirm": True}).data
        self.assertEqual((tab["rounds"][0]["status"], tab["total"]), ("confirmed", "120.00"))
        self.action(round_.pk, "complete")
        self.assertEqual(
            self.action(round_.pk, "amend", {"items": items}).data["error"], "round_closed"
        )

    def test_reject_carries_a_message_and_tab_close(self):
        token = self.takeout().data["access_token"]
        tab = Tab.objects.get(access_token=token)
        r = self.action(tab.rounds.get().pk, "reject", {"message": "牛肉賣完了"})
        self.assertEqual(r.data["rounds"][0]["shop_message"], "牛肉賣完了")
        status = self.web.get(f"/api/web/tabs/{token}/").data
        self.assertEqual(status["rounds"][0]["status_text"], "店家未接單")
        closed = self.console.post(f"/api/console/tabs/{tab.pk}/close/", {}, format="json")
        self.assertIsNotNone(closed.data["closed_at"])

    def test_service_view_and_day_view(self):
        self.takeout()
        yesterday = Tab.objects.create(
            service_mode=Tab.DINE_IN,
            table=self.table,
            business_date=hours.business_date() - timedelta(days=1),
        )
        Tab.objects.create(
            service_mode=Tab.TAKEOUT,
            phone="1",
            pickup_code="9",
            business_date=hours.business_date() - timedelta(days=2),
            closed_at=timezone.now(),
        )
        service = self.console.get("/api/console/tabs/").data
        self.assertEqual(len(service), 2)  # today's order and yesterday's still-open table
        self.assertIn(str(yesterday.pk), [t["id"] for t in service])
        old = self.console.get(
            "/api/console/tabs/", {"date": str(hours.business_date() - timedelta(days=2))}
        ).data
        self.assertEqual(len(old), 1)
        self.assertEqual(self.console.get("/api/console/tabs/", {"date": "bad"}).status_code, 400)

    def test_console_is_members_only(self):
        self.assertEqual(self.agent.get("/api/console/tabs/").status_code, 403)
        self.assertEqual(self.web.get("/api/console/tabs/").status_code, 403)
        owner = APIClient()
        owner.force_login(self.owner)
        self.assertEqual(owner.get("/api/console/tabs/").status_code, 200)

    def test_menu_and_tables_are_managed_and_audited(self):
        r = self.console.post("/api/console/categories/", {"name": "甜點"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        r = self.console.post(
            "/api/console/menu-items/",
            {"category": r.data["id"], "name": "布丁", "price": "45", "guidance": "推薦給小朋友"},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.data)
        r = self.console.patch(
            f"/api/console/menu-items/{r.data['id']}/", {"availability": "sold_out"}, format="json"
        )
        self.assertEqual(r.data["availability"], "sold_out")
        self.assertEqual(
            self.console.post(
                "/api/console/menu-items/",
                {"category": str(self.mains.pk), "name": "負價", "price": "-1"},
                format="json",
            ).status_code,
            400,
        )
        self.assertEqual(
            self.console.post("/api/console/tables/", {"code": "A1"}, format="json").status_code,
            400,
        )
        self.assertEqual(
            self.console.delete(f"/api/console/tables/{self.table.pk}/").status_code, 405
        )
        self.assertTrue(AuditEvent.objects.filter(action="menuitem.updated").exists())

    def test_settings_and_weekly_hours(self):
        r = self.console.patch(
            "/api/console/ordering-settings/",
            {"currency": "usd", "last_order_minutes_before_close": 30},
            format="json",
        )
        self.assertEqual(
            (r.data["currency"], r.data["last_order_minutes_before_close"]), ("USD", 30)
        )
        self.assertEqual(
            self.console.patch(
                "/api/console/ordering-settings/",
                {"last_order_minutes_before_close": 500},
                format="json",
            ).status_code,
            400,
        )
        week = [
            {
                "weekday": d,
                "intervals": [
                    {"opens_at": "11:00", "closes_at": "14:00"},
                    {"opens_at": "17:00", "closes_at": "21:00"},
                ],
            }
            for d in range(7)
        ]
        r = self.console.put("/api/console/hours/", {"weekly": week}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(BusinessHours.objects.count(), 14)
        for bad in [
            week[:6],
            [{**week[0], "intervals": [{"opens_at": "12:00", "closes_at": "11:00"}]}] + week[1:],
            [
                {
                    **week[0],
                    "intervals": [
                        {"opens_at": "11:00", "closes_at": "14:00"},
                        {"opens_at": "13:00", "closes_at": "15:00"},
                    ],
                }
            ]
            + week[1:],
        ]:
            self.assertEqual(
                self.console.put("/api/console/hours/", {"weekly": bad}, format="json").status_code,
                400,
            )
        self.assertEqual(BusinessHours.objects.count(), 14)

    # ---- Agent ----

    def test_agent_reads_store_and_menu_with_guidance(self):
        self.burger.guidance = "想配飲料的客人推薦套餐"
        self.burger.save()
        self.tea.availability = MenuItem.SOLD_OUT
        self.tea.save()
        shop = self.agent.get("/api/agent-api/shop/").data
        self.assertTrue(shop["accepting_orders"])
        menu_data = self.agent.get("/api/agent-api/menu/").data
        burger = menu_data["categories"][0]["items"][0]
        self.assertEqual((burger["price"], burger["shop_says"]), ("120", "想配飲料的客人推薦套餐"))
        tea = menu_data["categories"][1]["items"][0]
        self.assertEqual((tea["available"], tea["unavailable_reason"]), (False, "已售完"))

    def test_new_customer_needs_a_name_once(self):
        r = self.draft()
        self.assertEqual(r.data["error"], "new_customer_name_required")
        self.assertFalse(OrderDraft.objects.exists())
        r = self.draft(customer_name="王小姐")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "pending_confirmation")
        self.assertEqual(self.draft().data["customer_name"], "王小姐")
        self.assertEqual(self.draft(ref="guest", customer_name="x").status_code, 400)
        self.assertEqual(CustomerIdentity.objects.get().agenrena_customer_ref, REF_A)

    def test_draft_becomes_one_order_only_when_the_customer_confirms(self):
        token = self.token(self.draft(customer_name="Ada", note="六點到"))
        self.assertEqual(Tab.objects.count(), 0)
        page = self.web.get(f"/api/web/order-drafts/{token}/").data
        self.assertEqual((page["status"], page["note"]), ("pending", "六點到"))
        self.assertNotIn(REF_A, str(page))
        self.assertEqual(
            self.web.post(f"/api/web/order-drafts/{token}/confirm/", {}, format="json").data[
                "error"
            ],
            "phone_required",
        )
        first = self.web.post(
            f"/api/web/order-drafts/{token}/confirm/", {"phone": "0911"}, format="json"
        )
        again = self.web.post(
            f"/api/web/order-drafts/{token}/confirm/", {"phone": "0911"}, format="json"
        )
        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertEqual(first.data["access_token"], again.data["access_token"])
        self.assertEqual(Tab.objects.count(), 1)
        tab = Tab.objects.get()
        self.assertEqual(
            (tab.customer.agenrena_customer_ref, tab.rounds.get().source), (REF_A, "agent")
        )
        self.assertEqual(
            self.web.get(f"/api/web/order-drafts/{token}/").data["status"], "submitted"
        )
        self.assertEqual(self.web.get("/api/web/order-drafts/unknown/").status_code, 404)

    def test_customer_may_adjust_the_cart_before_confirming(self):
        token = self.token(self.draft(customer_name="Ada"))
        r = self.web.post(
            f"/api/web/order-drafts/{token}/confirm/",
            {"phone": "0911", "items": [{"item": str(self.tea.pk), "quantity": 3}]},
            format="json",
        )
        self.assertEqual(r.data["rounds"][0]["items"][0]["name"], "紅茶")
        self.assertEqual(
            OrderDraft.objects.get().items, [{"item": str(self.tea.pk), "quantity": 3}]
        )

    def test_expired_link_is_refused(self):
        token = self.token(self.draft(customer_name="Ada"))
        OrderDraft.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.web.get(f"/api/web/order-drafts/{token}/").data["status"], "expired")
        r = self.web.post(
            f"/api/web/order-drafts/{token}/confirm/", {"phone": "0911"}, format="json"
        )
        self.assertEqual(r.data["error"], "draft_expired")

    def test_agent_sees_and_cancels_only_its_customers_pending_orders(self):
        token = self.token(self.draft(customer_name="Ada"))
        self.web.post(f"/api/web/order-drafts/{token}/confirm/", {"phone": "0911"}, format="json")
        self.takeout()  # an anonymous QR order is nobody's to list
        orders = self.agent.get("/api/agent-api/orders/", {"customer_ref": REF_A}).data["orders"]
        self.assertEqual(
            [(o["status_text"], o["pickup_code"], o["total"]) for o in orders],
            [("等待店家確認", "1", "240")],
        )
        order_id = orders[0]["id"]
        self.assertEqual(
            self.agent.get("/api/agent-api/orders/", {"customer_ref": REF_B}).data["orders"], []
        )
        self.assertEqual(
            self.agent.get(
                f"/api/agent-api/orders/{order_id}/", {"customer_ref": REF_B}
            ).status_code,
            404,
        )
        self.assertEqual(
            self.agent.post(
                f"/api/agent-api/orders/{order_id}/cancel/", {"customer_ref": REF_B}, format="json"
            ).status_code,
            404,
        )
        r = self.agent.post(
            f"/api/agent-api/orders/{order_id}/cancel/", {"customer_ref": REF_A}, format="json"
        )
        self.assertEqual(r.data["status"], "cancelled")
        self.assertIsNotNone(Tab.objects.get(pk=order_id).closed_at)
        # Repeating is safe.
        self.assertEqual(
            self.agent.post(
                f"/api/agent-api/orders/{order_id}/cancel/", {"customer_ref": REF_A}, format="json"
            ).data["status"],
            "cancelled",
        )

    def test_agent_cannot_cancel_after_the_shop_confirms(self):
        token = self.token(self.draft(customer_name="Ada"))
        self.web.post(f"/api/web/order-drafts/{token}/confirm/", {"phone": "0911"}, format="json")
        tab = Tab.objects.get()
        self.action(tab.rounds.get().pk, "confirm")
        r = self.agent.post(
            f"/api/agent-api/orders/{tab.pk}/cancel/", {"customer_ref": REF_A}, format="json"
        )
        self.assertEqual(
            (r.data["error"], r.data["next_steps"]), ("already_confirmed", "請聯絡店家。")
        )

    def test_agent_cannot_reach_console_or_name_prices(self):
        r = self.draft(
            customer_name="Ada", items=[{"item": str(self.burger.pk), "unit_price": "1"}]
        )
        self.assertEqual(r.status_code, 409)
        self.assertEqual(
            self.agent.post("/api/console/categories/", {"name": "x"}, format="json").status_code,
            403,
        )


@override_settings(AGENRENA_VENDOR_ID="vendor-1", AGENRENA_VENDOR_SECRET="bvs_private")
class OrderNotificationTests(TestCase):
    def setUp(self):
        from core.tests.test_agenrena import FakeAgenrena

        menu(self)
        cache.clear()
        self.platform = FakeAgenrena()
        patcher = patch("core.agenrena._request", self.platform)
        patcher.start()
        self.addCleanup(patcher.stop)
        AgenrenaConnection.objects.create(status="connected", grant_id="grant-store")
        owner = get_user_model().objects.create_user(username="owner", password=PASSWORD)
        Membership.objects.create(user=owner, role="owner")
        self.console = APIClient()
        self.console.force_login(owner)
        _, secret = AgentKey.issue("Store Agent", AgentRole.objects.get(pk="customer_service"))
        self.agent = APIClient()
        self.agent.credentials(HTTP_AUTHORIZATION="Bearer " + secret)

    def sent(self):
        return [c["body"] for c in self.platform.calls if c["path"].endswith("/messages/send/")]

    def agenrena_order(self):
        with self.captureOnCommitCallbacks(execute=True):
            r = self.agent.post(
                "/api/agent-api/order-drafts/",
                {
                    "customer_ref": REF_A,
                    "customer_name": "Ada",
                    "items": [{"item": str(self.burger.pk)}],
                },
                format="json",
            )
            token = r.data["confirmation_url"].rsplit("/d/", 1)[1]
            APIClient().post(
                f"/api/web/order-drafts/{token}/confirm/", {"phone": "0911"}, format="json"
            )
            APIClient().post(
                f"/api/web/order-drafts/{token}/confirm/", {"phone": "0911"}, format="json"
            )
        return Tab.objects.get(customer__isnull=False).rounds.get()

    def act(self, round_, action, data=None):
        with self.captureOnCommitCallbacks(execute=True):
            return self.console.post(
                f"/api/console/rounds/{round_.pk}/{action}/", data or {}, format="json"
            )

    def test_order_progress_reaches_the_conversation(self):
        round_ = self.agenrena_order()
        self.act(round_, "amend", {"items": [{"item": str(self.chicken.pk)}]})
        self.act(round_, "confirm")
        self.act(round_, "complete")
        sent = self.sent()
        self.assertEqual(
            [m["card"]["header"] for m in sent],
            ["訂單已送出", "訂單已修改", "店家已接單", "餐點已完成"],
        )
        self.assertEqual({m["customer_ref"] for m in sent}, {REF_A})
        rows = {r["label"]: r["value"] for r in sent[0]["card"]["content"]}
        self.assertEqual(rows, {"取餐號": "1", "餐點": "牛肉堡×1", "金額": "TWD 120"})
        self.assertEqual(len({m["client_message_id"] for m in sent}), 4)
        self.assertNotIn("0911", str(sent))

    def test_rejection_reason_is_passed_on(self):
        round_ = self.agenrena_order()
        self.act(round_, "reject", {"message": "今天牛肉賣完了"})
        message = self.sent()[-1]
        self.assertEqual(message["card"]["status"], "cancelled")
        self.assertIn("今天牛肉賣完了", message["text"])

    def test_anonymous_qr_orders_are_not_messaged(self):
        with self.captureOnCommitCallbacks(execute=True):
            r = APIClient().post(
                "/api/web/orders/",
                {"phone": "0911", "items": [{"item": str(self.burger.pk)}]},
                format="json",
            )
        round_ = Tab.objects.get(access_token=r.data["access_token"]).rounds.get()
        self.act(round_, "confirm")
        self.assertEqual(self.sent(), [])

    def test_delivery_failure_keeps_the_order(self):
        self.platform.send_error = (503, {"error": {"code": "INTERNAL_ERROR"}})
        round_ = self.agenrena_order()
        self.assertEqual(round_.status, Round.PENDING)
        self.assertTrue(AuditEvent.objects.filter(action="agenrena.message_failed").exists())


class PickupConcurrencyTests(TransactionTestCase):
    def test_simultaneous_takeouts_get_distinct_numbers(self):
        menu(self)

        def place(_):
            close_old_connections()
            try:
                return place_takeout(
                    parse_lines([{"item": str(self.burger.pk)}]), phone="09"
                ).pickup_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=4) as pool:
            codes = list(pool.map(place, range(8)))
        self.assertEqual(sorted(codes, key=int), [str(n) for n in range(1, 9)])
        self.assertEqual(Tab.objects.count(), 8)
        self.assertEqual(
            Decimal(sum(t.rounds.get().total for t in Tab.objects.all())), Decimal("960")
        )
