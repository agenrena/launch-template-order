"""The store on Agenrena: this App is its Vendor and the store grants it once.
The platform is faked at the HTTP layer."""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import AgenrenaConnection, AuditEvent, CustomerIdentity, Membership
from core.services import deliver_to_customer, notify_customer

from .test_core import PASSWORD, ref

A = ref(0xA)
VENDOR = {"AGENRENA_VENDOR_ID": "vendor-1", "AGENRENA_VENDOR_SECRET": "bvs_private_vendor_secret"}
CARD = {
    "status": "success",
    "header": "店家已接單",
    "content": [{"label": "取餐號", "value": "12"}],
}


class FakeAgenrena:
    """Just enough of the Business Integration API, recording each call."""

    def __init__(self):
        self.calls = []
        self.tokens = 0
        self.session = {"status": "pending"}
        self.reject_token_once = False
        self.send_error = None

    def __call__(self, method, path, body=None, *, token="", grant_id=""):
        self.calls.append({"method": method, "path": path, "body": body, "grant_id": grant_id})
        if path == "/api/business-api/token/":
            self.tokens += 1
            return 200, {
                "access_token": f"bit_{self.tokens}",
                "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
            }
        if self.reject_token_once and token == "bit_1":
            self.reject_token_once = False
            return 401, {"error": {"code": "INTEGRATION_TOKEN_INVALID"}}
        if path == "/api/business-api/authorize/start/":
            return 201, {
                "session_id": str(uuid.uuid4()),
                "authorize_url": "https://agenrena.com/business/authorize/?token=bct_once",
                "expires_at": (timezone.now() + timedelta(minutes=5)).isoformat(),
            }
        if path.startswith("/api/business-api/authorize/session/"):
            return 200, self.session
        if path.startswith("/api/business-api/grants/"):
            return 204, {}
        if path == "/api/business-api/messages/send/":
            if self.send_error:
                return self.send_error
            return 200, {"id": "message"}
        return 404, {"error": {"code": "NOT_FOUND"}}

    def completed(self, grant_id="grant-A", name="大安店"):
        self.session = {"status": "completed", "grant_id": grant_id, "business_name": name}

    def paths(self, method=None):
        return [c["path"] for c in self.calls if method in (None, c["method"])]


@override_settings(**VENDOR)
class AgenrenaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user(username="owner", password=PASSWORD)
        Membership.objects.create(user=cls.owner, role="owner")
        cls.admin = User.objects.create_user(username="manager", password=PASSWORD)
        Membership.objects.create(user=cls.admin, role="admin")

    def setUp(self):
        cache.clear()
        self.platform = FakeAgenrena()
        patcher = patch("core.agenrena._request", self.platform)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.owner_client = APIClient()
        self.owner_client.force_login(self.owner)
        self.admin_client = APIClient()
        self.admin_client.force_login(self.admin)

    def post(self, action, client=None):
        return (client or self.owner_client).post(
            f"/api/console/agenrena/{action}/", {}, format="json"
        )

    def connect(self, **completed):
        start = self.post("connect")
        self.assertEqual(start.status_code, 201, start.data)
        self.platform.completed(**completed)
        return self.post("check")

    def overview(self, client=None):
        return (client or self.owner_client).get("/api/console/agenrena/").json()

    def test_store_connects_its_business_profile(self):
        start = self.post("connect")
        self.assertEqual(start.status_code, 201)
        self.assertEqual(start["Cache-Control"], "no-store")
        self.assertIn("authorize_url", start.data)
        self.assertEqual(self.platform.calls[-1]["body"], {"scopes": ["messages:send"]})
        self.assertEqual(self.post("check").data["status"], "pending")
        self.platform.completed()
        done = self.post("check")
        self.assertEqual(done.data["status"], "connected")
        self.assertEqual(done.data["business_name"], "大安店")
        overview = self.overview()
        self.assertTrue(overview["configured"])
        self.assertEqual(overview["status"], "connected")
        self.assertEqual(overview["business_name"], "大安店")
        # The consent link is a bearer credential: never stored or audited.
        self.assertNotIn("bct_once", str(list(AgenrenaConnection.objects.values())))
        self.assertNotIn("bct_once", str(list(AuditEvent.objects.values())))
        self.assertTrue(AuditEvent.objects.filter(action="agenrena.connected").exists())

    def test_expired_consent_returns_to_unconnected(self):
        self.post("connect")
        self.platform.session = {"status": "expired"}
        self.assertEqual(self.post("check").data["status"], "expired")
        self.assertIsNone(AgenrenaConnection.current())

    def test_connected_store_must_disconnect_before_reconnecting(self):
        self.connect()
        self.assertEqual(self.post("connect").status_code, 409)

    def test_disconnect_hands_the_grant_back(self):
        self.connect()
        self.assertEqual(self.post("disconnect").status_code, 200)
        self.assertEqual(self.platform.paths("DELETE"), ["/api/business-api/grants/grant-A/"])
        self.assertIsNone(AgenrenaConnection.current())
        self.assertTrue(AuditEvent.objects.filter(action="agenrena.disconnected").exists())

    def test_admin_reads_status_but_only_owner_manages(self):
        self.assertEqual(self.admin_client.get("/api/console/agenrena/").status_code, 200)
        for action in ["connect", "check", "disconnect"]:
            self.assertEqual(self.post(action, self.admin_client).status_code, 403)
        self.assertEqual(self.platform.calls, [])

    @override_settings(AGENRENA_VENDOR_ID="", AGENRENA_VENDOR_SECRET="")
    def test_unconfigured_deployment_keeps_working_without_agenrena(self):
        self.assertEqual(self.overview(), {"configured": False, "status": "none"})
        self.assertEqual(self.post("connect").status_code, 400)
        identity = CustomerIdentity.objects.create(agenrena_customer_ref=A)
        self.assertFalse(deliver_to_customer(identity, "訂單已送出"))
        self.assertEqual(self.platform.calls, [])

    def test_platform_outage_is_reported_without_secrets(self):
        def down(*args, **kwargs):
            from core.agenrena import AgenrenaError

            raise AgenrenaError("UNAVAILABLE")

        with patch("core.agenrena._request", down):
            result = self.post("connect")
        self.assertEqual(result.status_code, 502)
        self.assertNotIn("bvs_private_vendor_secret", str(result.data))
        self.assertIsNone(AgenrenaConnection.current())

    def test_notification_is_sent_after_commit(self):
        self.connect()
        identity = CustomerIdentity.objects.create(agenrena_customer_ref=A)
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            notify_customer(identity, "店家已接單 · 取餐號 12", card=CARD, message_id="order-1")
        # Nothing is sent before the business write commits.
        self.assertNotIn("/api/business-api/messages/send/", self.platform.paths())
        for callback in callbacks:
            callback()
        sent = self.platform.calls[-1]
        self.assertEqual(sent["path"], "/api/business-api/messages/send/")
        self.assertEqual(sent["grant_id"], "grant-A")
        self.assertEqual(
            sent["body"],
            {
                "customer_ref": A,
                "text": "店家已接單 · 取餐號 12",
                "card": CARD,
                "client_message_id": "order-1",
            },
        )
        event = AuditEvent.objects.get(action="agenrena.message_sent")
        self.assertEqual(event.customer, identity)
        self.assertEqual(event.actor_type, "system")
        self.assertNotIn("取餐號", str(event.detail))

    def test_customer_without_reference_or_connection_is_skipped(self):
        manual = CustomerIdentity.objects.create(display_name="Walk-in")
        unconnected = CustomerIdentity.objects.create(agenrena_customer_ref=A)
        with self.captureOnCommitCallbacks(execute=True):
            notify_customer(manual, "x")
            notify_customer(unconnected, "x")
            notify_customer(None, "x")
        self.assertEqual(self.platform.calls, [])

    def test_store_revoking_the_app_stops_delivery(self):
        self.connect()
        identity = CustomerIdentity.objects.create(agenrena_customer_ref=A)
        self.platform.send_error = (403, {"error": {"code": "INTEGRATION_GRANT_REVOKED"}})
        self.assertFalse(deliver_to_customer(identity, "x"))
        self.assertEqual(AgenrenaConnection.current().status, "revoked")
        self.assertEqual(
            AuditEvent.objects.get(action="agenrena.message_failed").detail,
            {"error": "INTEGRATION_GRANT_REVOKED"},
        )
        sends = len(self.platform.paths("POST"))
        self.assertFalse(deliver_to_customer(identity, "x"))
        self.assertEqual(len(self.platform.paths("POST")), sends)
        self.assertEqual(self.overview()["status"], "revoked")
        # Reconnecting starts a fresh authorization.
        self.assertEqual(self.connect().data["status"], "connected")

    def test_unknown_customer_is_a_failed_delivery_not_an_error(self):
        self.connect()
        identity = CustomerIdentity.objects.create(agenrena_customer_ref=A)
        self.platform.send_error = (
            400,
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "fields": {"customer_ref": [{"code": "CUSTOMER_NOT_FOUND"}]},
                }
            },
        )
        self.assertFalse(deliver_to_customer(identity, "x"))
        self.assertEqual(AgenrenaConnection.current().status, "connected")
        self.assertEqual(
            AuditEvent.objects.get(action="agenrena.message_failed").detail,
            {"error": "CUSTOMER_NOT_FOUND"},
        )

    def test_vendor_token_is_cached_and_refreshed_once_when_rejected(self):
        self.connect()
        self.assertEqual(self.platform.tokens, 1)
        identity = CustomerIdentity.objects.create(agenrena_customer_ref=A)
        self.platform.reject_token_once = True
        self.assertTrue(deliver_to_customer(identity, "x"))
        self.assertEqual(self.platform.tokens, 2)
        token_calls = [c for c in self.platform.calls if c["path"].endswith("/token/")]
        self.assertEqual(token_calls[0]["body"]["vendor_id"], "vendor-1")
        self.assertNotIn(
            "bvs_private_vendor_secret",
            str(list(AuditEvent.objects.values())) + str(self.overview()),
        )
