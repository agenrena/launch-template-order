import json
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.branding import initial_software_name
from core.models import Business, Membership


class SoftwareNameTests(TestCase):
    def test_download_name_and_invalid_configuration_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "app-config.json"
            with override_settings(SOFTWARE_CONFIG_FILE=path):
                self.assertEqual(initial_software_name(), settings.SOFTWARE_DEFAULT_NAME)
                for value in (
                    "",
                    "{",
                    "[]",
                    '{"software_name":"  "}',
                    '{"software_name":42}',
                    json.dumps({"software_name": "x" * 121}),
                ):
                    path.write_text(value, encoding="utf-8")
                    self.assertEqual(initial_software_name(), settings.SOFTWARE_DEFAULT_NAME)
                path.write_bytes(b"\xff")
                self.assertEqual(initial_software_name(), settings.SOFTWARE_DEFAULT_NAME)
                name = '小林 "維修" 台 <script> $HOME'
                path.write_text(json.dumps({"software_name": "  " + name + "  "}), encoding="utf-8")
                Business.objects.all().delete()
                business = Business.current()
                self.assertEqual(business.software_name, name)
                path.write_text('{"software_name":"Changed seed"}', encoding="utf-8")
                self.assertEqual(Business.current().software_name, name)

    def test_public_session_name_and_authenticated_rename(self):
        client = APIClient()
        business = Business.current()
        original_shop_name = business.name
        response = client.get("/api/console/session/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["software_name"], business.software_name)
        self.assertIsNone(response.data["user"])
        self.assertEqual(
            client.patch("/api/console/business/", {"software_name": "Blocked"}).status_code, 403
        )
        user = get_user_model().objects.create_user(username="naming-owner")
        Membership.objects.create(user=user, role="owner")
        client.force_login(user)
        response = client.patch(
            "/api/console/business/", {"software_name": "我的維修台"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        business.refresh_from_db()
        self.assertEqual(business.name, original_shop_name)
        self.assertEqual(business.software_name, "我的維修台")
        self.assertEqual(
            client.patch(
                "/api/console/business/", {"software_name": "   "}, format="json"
            ).status_code,
            400,
        )
        client.logout()
        self.assertEqual(client.get("/api/console/session/").data["software_name"], "我的維修台")
