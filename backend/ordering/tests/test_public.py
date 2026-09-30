"""The customer entrance (config/public.py) and what happens before it is published."""

from io import BytesIO
from wsgiref.util import setup_testing_defaults

from config.public import public_only
from core.models import CustomerIdentity
from django.test import SimpleTestCase, TestCase, override_settings

from ordering.models import OrderDraft

from . import test_ordering as base


class EntranceTests(SimpleTestCase):
    def reached(self, path, method="GET"):
        """Whether a request on the customer entrance gets through to the App."""
        calls = []

        def app(environ, start_response):
            calls.append(environ["PATH_INFO"])
            start_response("200 OK", [])
            return [b""]

        environ = {"PATH_INFO": path, "REQUEST_METHOD": method, "wsgi.input": BytesIO()}
        setup_testing_defaults(environ)
        statuses = []
        public_only(app)(environ, lambda status, headers: statuses.append(status))
        self.assertEqual(statuses[0][:3], "200" if calls else "404")
        return bool(calls)

    def test_ordering_pages_and_their_api_pass(self):
        for path in (
            "/",
            "/assets/index-abc.js",
            "/d/token",
            "/o/token",
            "/api/web/store/",
            "/api/web/orders/",
            "/api/web/tabs/token/rounds/",
            "/api/web/order-drafts/token/confirm/",
        ):
            with self.subTest(path):
                self.assertTrue(self.reached(path, "POST" if "rounds" in path else "GET"))

    def test_console_setup_agent_and_mcp_stay_private(self):
        for path in (
            "/console",
            "/console/",
            "/api/console/setup/",
            "/api/console/session/",
            "/api/console/keys/",
            "/api/agent-api/order-drafts/",
            "/mcp",
            "/health/",
            "/d/../api/console/setup/",
            "/api/web/../console/keys/",
        ):
            with self.subTest(path):
                self.assertFalse(self.reached(path, "POST"))


class NotPublishedTests(TestCase):
    # The ordering fixture, without inheriting (and re-running) its tests.
    setUp = base.OrderingTests.setUp
    draft = base.OrderingTests.draft

    @override_settings(LOCAL_APP=True, ORDER_PUBLIC_BASE_URL="")
    def test_agent_gets_no_link_customers_cannot_open(self):
        response = self.draft(customer_name="小陳")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"], "not_published")
        self.assertFalse(OrderDraft.objects.exists())
        self.assertFalse(CustomerIdentity.objects.filter(agenrena_customer_ref=base.REF_A).exists())
        settings = self.console.get("/api/console/ordering-settings/").data
        self.assertEqual(settings["public_url"], "")

    @override_settings(LOCAL_APP=True, ORDER_PUBLIC_BASE_URL="https://order.example.com")
    def test_published_links_use_the_public_address(self):
        response = self.draft(customer_name="小陳")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            response.data["confirmation_url"].startswith("https://order.example.com/d/")
        )
        settings = self.console.get("/api/console/ordering-settings/").data
        self.assertEqual(settings["public_url"], "https://order.example.com")

    def test_hosted_defaults_to_this_site(self):
        settings = self.console.get("/api/console/ordering-settings/").data
        self.assertEqual(settings["public_url"], "http://testserver")
