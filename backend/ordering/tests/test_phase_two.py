"""Options (one level), pausing orders and today's numbers."""

from datetime import timedelta
from unittest.mock import patch

from core.models import AgenrenaConnection, AgentKey, AgentRole, AuditEvent, Membership
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from ordering.models import MenuItem, Option, OptionGroup, OrderingSettings, Round, Tab

from .test_ordering import PASSWORD, REF_A, menu


class PhaseTwoTests(TestCase):
    def setUp(self):
        menu(self)
        self.milk_tea = MenuItem.objects.create(category=self.drinks, name="奶茶", price=50)
        self.sugar = OptionGroup.objects.create(name="甜度", min_select=1, max_select=1)
        self.full, self.half, self.none = (
            Option.objects.create(group=self.sugar, name=name, sort_order=i)
            for i, name in enumerate(["正常", "半糖", "無糖"])
        )
        self.toppings = OptionGroup.objects.create(name="加料", min_select=0, max_select=2)
        self.pearl = Option.objects.create(group=self.toppings, name="珍珠", price_delta=10)
        self.jelly = Option.objects.create(group=self.toppings, name="椰果", price_delta=10)
        self.milk_tea.option_groups.set([self.sugar, self.toppings])
        owner = get_user_model().objects.create_user(username="owner", password=PASSWORD)
        Membership.objects.create(user=owner, role="owner")
        self.console = APIClient()
        self.console.force_login(owner)
        self.web = APIClient()
        _, secret = AgentKey.issue("Store Agent", AgentRole.objects.get(pk="customer_service"))
        self.agent = APIClient()
        self.agent.credentials(HTTP_AUTHORIZATION="Bearer " + secret)
        cache.clear()

    def line(self, *options, quantity=1):
        return {
            "item": str(self.milk_tea.pk),
            "quantity": quantity,
            "options": [str(o.pk) for o in options],
        }

    def takeout(self, *lines):
        return self.web.post(
            "/api/web/orders/", {"phone": "0911", "items": list(lines)}, format="json"
        )

    # ---- Options ----

    def test_options_are_priced_and_copied_onto_the_order(self):
        r = self.takeout(self.line(self.half, self.pearl, self.jelly, quantity=2))
        self.assertEqual(r.status_code, 201, r.data)
        line = r.data["rounds"][0]["items"][0]
        self.assertEqual(line["total"], "140.00")  # (50 + 10 + 10) × 2
        self.assertEqual(
            [(c["group"], c["name"]) for c in line["choices"]],
            [("甜度", "半糖"), ("加料", "珍珠"), ("加料", "椰果")],
        )
        self.pearl.name, self.pearl.price_delta = "黑糖珍珠", 20
        self.pearl.save()
        again = self.web.get(f"/api/web/tabs/{r.data['access_token']}/").data["rounds"][0]["items"][
            0
        ]
        self.assertEqual((again["choices"][1]["name"], again["total"]), ("珍珠", "140.00"))

    def test_option_rules_are_enforced_with_useful_refusals(self):
        missing = self.takeout(self.line(self.pearl))
        self.assertEqual(missing.data["error"], "option_required")
        self.assertIn("半糖", missing.data["next_steps"])
        self.assertEqual(
            self.takeout(self.line(self.full, self.half)).data["error"], "too_many_options"
        )
        foreign = OptionGroup.objects.create(name="熟度", min_select=0, max_select=1)
        medium = Option.objects.create(group=foreign, name="五分熟")
        self.assertEqual(
            self.takeout(self.line(self.full, medium)).data["error"], "option_not_offered"
        )
        self.assertEqual(
            self.takeout({"item": str(self.burger.pk), "options": [str(self.half.pk)]}).data[
                "error"
            ],
            "option_not_offered",
        )
        for bad in ["half", [1], [str(self.full.pk), str(self.full.pk)]]:
            r = self.takeout({"item": str(self.milk_tea.pk), "options": bad})
            self.assertEqual(r.data["error"], "bad_option", bad)
        self.assertEqual(Tab.objects.count(), 0)

    def test_sold_out_option_stops_customers_but_not_staff(self):
        tab = self.takeout(self.line(self.half)).data
        self.pearl.is_available = False
        self.pearl.save()
        refused = self.takeout(self.line(self.half, self.pearl))
        self.assertEqual(refused.data["error"], "option_unavailable")
        self.assertIn("椰果", refused.data["next_steps"])
        round_id = Tab.objects.get(access_token=tab["access_token"]).rounds.get().pk
        amended = self.console.post(
            f"/api/console/rounds/{round_id}/amend/",
            {"items": [self.line(self.half, self.pearl)]},
            format="json",
        )
        self.assertEqual(amended.status_code, 200, amended.data)
        choices = amended.data["rounds"][0]["items"][0]["choices"]
        self.assertEqual([c["option"] for c in choices], [str(self.half.pk), str(self.pearl.pk)])
        # Staff still answer required questions.
        r = self.console.post(
            f"/api/console/rounds/{round_id}/amend/", {"items": [self.line()]}, format="json"
        )
        self.assertEqual(r.data["error"], "option_required")

    def test_menus_describe_the_questions(self):
        tea = self.web.get("/api/web/store/").data["menu"][1]["items"][-1]
        self.assertEqual([g["name"] for g in tea["option_groups"]], ["甜度", "加料"])
        self.assertEqual(tea["option_groups"][1]["options"][0]["price_delta"], "10.00")
        agent_tea = self.agent.get("/api/agent-api/menu/").data["categories"][1]["items"][-1]
        self.assertEqual(
            [g["choose"] for g in agent_tea["options"]], ["必選 1 個", "可選，最多 2 個"]
        )
        self.assertEqual(
            agent_tea["options"][1]["choices"][0],
            {"id": str(self.pearl.pk), "name": "珍珠", "price_delta": "10", "available": True},
        )

    def test_agent_orders_with_options(self):
        r = self.agent.post(
            "/api/agent-api/order-drafts/",
            {
                "customer_ref": REF_A,
                "customer_name": "Ada",
                "items": [self.line(self.half, self.pearl)],
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.data)
        token = r.data["confirmation_url"].rsplit("/d/", 1)[1]
        draft = self.web.get(f"/api/web/order-drafts/{token}/").data
        self.assertEqual(draft["items"][0]["options"], [str(self.half.pk), str(self.pearl.pk)])
        self.web.post(f"/api/web/order-drafts/{token}/confirm/", {"phone": "0911"}, format="json")
        order = self.agent.get("/api/agent-api/orders/", {"customer_ref": REF_A}).data["orders"][0]
        item = order["items"][0]
        self.assertEqual((item["unit_price"], item["total"], order["total"]), ("60", "60", "60"))
        self.assertEqual(item["choices"], ["甜度：半糖", "加料：珍珠"])
        self.assertEqual(item["options"], [str(self.half.pk), str(self.pearl.pk)])
        missing = self.agent.post(
            "/api/agent-api/order-drafts/",
            {"customer_ref": REF_A, "items": [self.line()]},
            format="json",
        )
        self.assertEqual(missing.data["error"], "option_required")

    def test_option_groups_are_managed_with_their_choices(self):
        r = self.console.post(
            "/api/console/option-groups/",
            {
                "name": "冰塊",
                "min_select": 1,
                "max_select": 1,
                "options": [{"name": "正常冰"}, {"name": "少冰"}, {"name": "去冰"}],
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.data)
        ids = [o["id"] for o in r.data["options"]]
        # Reorder, rename, drop one, add one.
        r = self.console.patch(
            f"/api/console/option-groups/{r.data['id']}/",
            {
                "options": [
                    {"id": ids[2], "name": "去冰"},
                    {"id": ids[0], "name": "正常"},
                    {"name": "熱", "price_delta": "5"},
                ]
            },
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(
            [(o["name"], o["price_delta"]) for o in r.data["options"]],
            [("去冰", "0.00"), ("正常", "0.00"), ("熱", "5.00")],
        )
        self.assertFalse(Option.objects.filter(pk=ids[1]).exists())
        group_id = r.data["id"]
        for bad in [
            {"min_select": 2, "max_select": 1},
            {"max_select": 5},
            {"options": [{"name": "同名"}, {"name": "同名"}]},
            {"options": [{"id": str(self.pearl.pk), "name": "偷來的"}]},
            {"options": []},
        ]:
            self.assertEqual(
                self.console.patch(
                    f"/api/console/option-groups/{group_id}/", bad, format="json"
                ).status_code,
                400,
                bad,
            )
        r = self.console.patch(
            f"/api/console/menu-items/{self.tea.pk}/", {"option_groups": [group_id]}, format="json"
        )
        self.assertEqual(r.json()["option_groups"], [group_id])
        r = self.console.patch(
            f"/api/console/options/{self.pearl.pk}/", {"is_available": False}, format="json"
        )
        self.assertEqual(r.data["is_available"], False)
        self.assertEqual(
            self.console.patch(
                f"/api/console/options/{self.pearl.pk}/", {"name": "x"}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(self.agent.get("/api/console/option-groups/").status_code, 403)
        self.assertTrue(AuditEvent.objects.filter(action="optiongroup.updated").exists())

    # ---- Pausing ----

    def test_pause_stops_every_entrance_until_resumed(self):
        r = self.console.post(
            "/api/console/ordering-status/",
            {"action": "pause", "minutes": 30, "reason": "訂單較多"},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["paused"])
        self.assertIn("暫停接單：訂單較多。預計", r.data["closed_reason"])
        self.assertFalse(self.web.get("/api/web/store/").data["accepting_orders"])
        self.assertEqual(self.takeout(self.line(self.half)).data["error"], "not_accepting_orders")
        draft = self.agent.post(
            "/api/agent-api/order-drafts/",
            {"customer_ref": REF_A, "customer_name": "Ada", "items": [self.line(self.half)]},
            format="json",
        )
        self.assertIn("訂單較多", draft.data["message"])
        r = self.console.post("/api/console/ordering-status/", {"action": "resume"}, format="json")
        self.assertFalse(r.data["paused"])
        self.assertEqual(self.takeout(self.line(self.half)).status_code, 201)
        self.assertEqual(
            list(
                AuditEvent.objects.filter(action__startswith="ordering.")
                .values_list("action", flat=True)
                .order_by("created_at")
            ),
            ["ordering.paused", "ordering.resumed"],
        )

    def test_timed_pause_ends_by_itself_and_manual_pause_does_not(self):
        self.console.post(
            "/api/console/ordering-status/", {"action": "pause", "minutes": 15}, format="json"
        )
        OrderingSettings.objects.update(paused_until=timezone.now() - timedelta(seconds=1))
        self.assertTrue(self.web.get("/api/web/store/").data["accepting_orders"])
        self.console.post(
            "/api/console/ordering-status/", {"action": "pause", "minutes": None}, format="json"
        )
        status = self.console.get("/api/console/ordering-status/").data
        self.assertEqual((status["paused"], status["paused_until"]), (True, None))
        self.assertIn("請稍後再試", status["closed_reason"])
        for bad in [
            {"action": "pause", "minutes": 7},
            {"action": "stop"},
            {"action": "pause", "reason": "x" * 121},
        ]:
            self.assertEqual(
                self.console.post("/api/console/ordering-status/", bad, format="json").status_code,
                400,
                bad,
            )

    # ---- Today ----

    def test_today_counts_billed_orders_only(self):
        tabs = [
            self.takeout(self.line(self.half, self.pearl)).data["access_token"] for _ in range(3)
        ]
        rounds = [Tab.objects.get(access_token=t).rounds.get() for t in tabs]
        rounds[0].set_status(Round.CONFIRMED)
        rounds[1].set_status(Round.COMPLETED)
        rounds[2].set_status(Round.REJECTED)
        self.takeout(self.line(self.half))  # still pending
        today = self.console.get("/api/console/sales/today/").data
        self.assertEqual((today["orders"], today["revenue"], today["pending"]), (2, "120.00", 1))
        self.assertEqual(self.agent.get("/api/console/sales/today/").status_code, 403)


@override_settings(AGENRENA_VENDOR_ID="vendor-1", AGENRENA_VENDOR_SECRET="bvs_private")
class OptionNotificationTests(TestCase):
    def test_card_names_the_options(self):
        from core.tests.test_agenrena import FakeAgenrena

        menu(self)
        cache.clear()
        platform = FakeAgenrena()
        with patch("core.agenrena._request", platform):
            AgenrenaConnection.objects.create(status="connected", grant_id="grant-store")
            tea = MenuItem.objects.create(category=self.drinks, name="奶茶", price=50)
            group = OptionGroup.objects.create(name="甜度", min_select=1, max_select=1)
            half = Option.objects.create(group=group, name="半糖")
            tea.option_groups.add(group)
            _, secret = AgentKey.issue("Store Agent", AgentRole.objects.get(pk="customer_service"))
            agent = APIClient()
            agent.credentials(HTTP_AUTHORIZATION="Bearer " + secret)
            with self.captureOnCommitCallbacks(execute=True):
                r = agent.post(
                    "/api/agent-api/order-drafts/",
                    {
                        "customer_ref": REF_A,
                        "customer_name": "Ada",
                        "items": [{"item": str(tea.pk), "options": [str(half.pk)]}],
                    },
                    format="json",
                )
                token = r.data["confirmation_url"].rsplit("/d/", 1)[1]
                APIClient().post(
                    f"/api/web/order-drafts/{token}/confirm/", {"phone": "0911"}, format="json"
                )
        sent = [c["body"] for c in platform.calls if c["path"].endswith("/messages/send/")]
        rows = {row["label"]: row["value"] for row in sent[0]["card"]["content"]}
        self.assertEqual(rows["餐點"], "奶茶（半糖）×1")
