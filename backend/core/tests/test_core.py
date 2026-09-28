import io
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, transaction
from django.test import TestCase, TransactionTestCase
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from core.models import (
    AgentKey,
    AgentPermission,
    AgentRole,
    AuditEvent,
    Business,
    CustomerIdentity,
    Membership,
)
from core.permissions import agent_actor, authorize, human_actor
from core.services import save_member, update_customer_profile

PASSWORD = "Testing-private-password-739!"


def ref(n):
    """A reference in Agenrena's format: bcr_ + 32 hex."""
    return f"bcr_{n:032x}"


A, B, NEW = ref(0xA), ref(0xB), ref(0x1)


class CoreTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user(username="owner", password=PASSWORD)
        Membership.objects.create(user=cls.owner, role="owner")
        cls.admin = User.objects.create_user(username="manager", password=PASSWORD)
        Membership.objects.create(user=cls.admin, role="admin")
        cls.role = AgentRole.objects.get(pk="customer_service")
        cls.key, cls.secret = AgentKey.issue("Customer agent", cls.role)

    def setUp(self):
        self.owner_client = APIClient()
        self.owner_client.force_login(self.owner)
        self.admin_client = APIClient()
        self.admin_client.force_login(self.admin)
        self.agent = APIClient()
        self.agent.credentials(HTTP_AUTHORIZATION="Bearer " + self.secret)

    def test_initial_defaults_are_minimal(self):
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(AgentRole.objects.count(), 1)
        self.assertEqual(
            set(self.role.permissions.values_list("code", flat=True)),
            {
                "business.read",
                "customer.profile.read",
                "customer.profile.write",
                "menu.read",
                "order.read",
                "order.create",
                "order.cancel",
            },
        )
        self.assertEqual(CustomerIdentity.objects.count(), 0)

    def test_single_business_and_optional_unique_reference(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Business.objects.create(pk=2)
        CustomerIdentity.objects.create()
        CustomerIdentity.objects.create()
        CustomerIdentity.objects.create(agenrena_customer_ref=A)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CustomerIdentity.objects.create(agenrena_customer_ref=A)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CustomerIdentity.objects.create(agenrena_customer_ref="")

    def test_login_csrf_and_account_membership(self):
        c = APIClient(enforce_csrf_checks=True)
        self.assertEqual(
            c.post("/api/console/login/", {"username": "owner", "password": PASSWORD}).status_code,
            403,
        )
        token = c.get("/api/console/session/").json()["csrf_token"]
        result = c.post(
            "/api/console/login/",
            {"username": "owner", "password": PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["user"]["role"], "owner")
        self.assertEqual(c.patch("/api/console/business/", {"name": "Test"}).status_code, 403)
        self.assertEqual(
            c.patch(
                "/api/console/business/",
                {"name": "Test"},
                format="json",
                HTTP_X_CSRFTOKEN=result.data["csrf_token"],
            ).status_code,
            200,
        )
        get_user_model().objects.create_superuser(username="unassigned", password=PASSWORD)
        self.assertEqual(
            APIClient()
            .post("/api/console/login/", {"username": "unassigned", "password": PASSWORD})
            .status_code,
            403,
        )

    def test_agent_cannot_access_console_and_human_cannot_access_agent(self):
        self.assertEqual(self.agent.get("/api/console/business/").status_code, 403)
        self.assertEqual(self.owner_client.get("/api/agent-api/business/").status_code, 401)
        self.assertEqual(APIClient().get("/api/agent-api/business/").status_code, 401)

    def test_admin_can_edit_business_but_not_manage_access(self):
        self.assertEqual(
            self.admin_client.patch(
                "/api/console/business/", {"name": "Studio"}, format="json"
            ).status_code,
            200,
        )
        for path in ["members/", "keys/", "agent-roles/"]:
            self.assertEqual(self.admin_client.get("/api/console/" + path).status_code, 403)
        self.assertEqual(
            self.admin_client.post(
                "/api/console/keys/",
                {"label": "bad", "role": self.role.pk},
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(self.admin_client.get("/api/console/audit/").status_code, 200)

    def test_owner_create_member_and_password_is_hashed(self):
        result = self.owner_client.post(
            "/api/console/members/",
            {
                "username": "helper",
                "password": PASSWORD,
                "name": "Helper",
                "role": "admin",
            },
            format="json",
        )
        self.assertEqual(result.status_code, 201, result.data)
        user = get_user_model().objects.get(username="helper")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertNotIn("password", result.data)
        self.assertEqual(user.membership.role, "admin")
        self.assertEqual(
            self.owner_client.post(
                "/api/console/members/",
                {"username": "short", "password": "123", "role": "owner"},
                format="json",
            ).status_code,
            400,
        )

    def test_cannot_remove_last_owner_and_can_disable_admin(self):
        for values in [{"role": "admin"}, {"is_active": False}]:
            result = self.owner_client.patch(
                f"/api/console/members/{self.owner.pk}/", values, format="json"
            )
            self.assertEqual(result.status_code, 400)
        result = self.owner_client.patch(
            f"/api/console/members/{self.admin.pk}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.admin_client.get("/api/console/business/").status_code, 403)
        self.assertIsNone(self.admin_client.get("/api/console/session/").data["user"])

    def test_role_changes_apply_to_existing_session(self):
        second = get_user_model().objects.create_user(username="second", password=PASSWORD)
        Membership.objects.create(user=second, role="owner")
        save_member(human_actor(second), {"role": "admin"}, self.owner.pk)
        self.assertEqual(self.owner_client.get("/api/console/keys/").status_code, 403)

    def test_password_change_checks_old_and_preserves_current_session(self):
        c = APIClient()
        self.assertEqual(
            c.post("/api/console/login/", {"username": "owner", "password": PASSWORD}).status_code,
            200,
        )
        other = APIClient()
        other.login(username="owner", password=PASSWORD)
        self.assertEqual(
            c.post(
                "/api/console/password/",
                {"old_password": "wrong", "password": "Changed-password-82!"},
                format="json",
            ).status_code,
            400,
        )
        result = c.post(
            "/api/console/password/",
            {"old_password": PASSWORD, "password": "Changed-password-82!"},
            format="json",
        )
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(c.get("/api/console/business/").status_code, 200)
        self.assertEqual(other.get("/api/console/business/").status_code, 403)

    def test_key_secret_once_revocation_and_audit_redaction(self):
        result = self.owner_client.post(
            "/api/console/keys/",
            {"label": "New", "role": "customer_service"},
            format="json",
        )
        self.assertEqual(result.status_code, 201)
        secret = result.data["secret"]
        key_id = result.data["id"]
        listing = self.owner_client.get("/api/console/keys/").json()
        self.assertNotIn(secret, str(listing))
        self.assertNotIn("digest", str(listing))
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer " + secret)
        self.assertEqual(c.get("/api/agent-api/session/").status_code, 200)
        self.owner_client.post(f"/api/console/keys/{key_id}/revoke/", {}, format="json")
        self.assertEqual(c.get("/api/agent-api/session/").status_code, 401)
        self.assertNotIn(secret, str(list(AuditEvent.objects.values())))
        self.assertNotIn(PASSWORD, str(list(AuditEvent.objects.values())))

    def test_permission_removal_and_scope_change_take_effect(self):
        permission = AgentPermission.objects.get(pk="customer.profile.read")
        self.role.permissions.remove(permission)
        self.assertEqual(
            self.agent.get("/api/agent-api/customer-profile/", {"customer_ref": A}).status_code,
            403,
        )
        self.role.permissions.add(permission)
        permission.scope = "business"
        permission.save()
        self.assertEqual(
            self.agent.get("/api/agent-api/customer-profile/", {"customer_ref": A}).status_code,
            403,
        )
        with self.assertRaises(PermissionDenied):
            authorize(agent_actor(self.key), "unknown")
        with self.assertRaises(PermissionDenied):
            authorize(agent_actor(self.key), "business.write")

    def test_customer_read_is_scoped_and_does_not_create(self):
        a = CustomerIdentity.objects.create(agenrena_customer_ref=A, display_name="A")
        CustomerIdentity.objects.create(agenrena_customer_ref=B, display_name="B")
        result = self.agent.get("/api/agent-api/customer-profile/", {"customer_ref": A})
        self.assertEqual(result.data["profile"], {"id": str(a.pk), "display_name": "A"})
        self.assertIsNone(
            self.agent.get("/api/agent-api/customer-profile/", {"customer_ref": NEW}).data[
                "profile"
            ]
        )
        self.assertEqual(CustomerIdentity.objects.count(), 2)
        self.assertNotIn("agenrena_customer_ref", result.data["profile"])

    def test_customer_update_is_repeatable_without_name_matching(self):
        manual = CustomerIdentity.objects.create(display_name="Same name")
        data = {"customer_ref": A, "display_name": "Same name"}
        one = self.agent.post("/api/agent-api/customer-profile/", data, format="json")
        two = self.agent.post("/api/agent-api/customer-profile/", data, format="json")
        self.assertEqual(one.status_code, 200, one.data)
        self.assertEqual(one.data, two.data)
        self.assertNotEqual(str(manual.pk), one.data["profile"]["id"])
        b = CustomerIdentity.objects.create(agenrena_customer_ref=B, display_name="B")
        self.agent.post(
            "/api/agent-api/customer-profile/",
            {**data, "display_name": "Changed"},
            format="json",
        )
        b.refresh_from_db()
        self.assertEqual(b.display_name, "B")
        self.assertEqual(
            CustomerIdentity.objects.filter(agenrena_customer_ref=A).count(),
            1,
        )
        event = AuditEvent.objects.filter(action="customer.profile_updated").first()
        self.assertEqual(str(event.customer_id), one.data["profile"]["id"])
        self.assertNotIn("Changed", str(event.detail))

    def test_profile_does_not_accept_internal_id_role_or_reference_override(self):
        for extra in [
            {"id": "other"},
            {"agenrena_customer_ref": "other"},
            {"role": "owner"},
        ]:
            result = self.agent.post(
                "/api/agent-api/customer-profile/",
                {"customer_ref": A, "display_name": "Ada", **extra},
                format="json",
            )
            self.assertEqual(result.status_code, 400)
        # Only Agenrena's format: invented references such as "guest" are refused.
        for bad in ["", "with spaces", "../other", "guest", A.upper(), A + "0", "bcr_short"]:
            self.assertEqual(
                self.agent.get(
                    "/api/agent-api/customer-profile/", {"customer_ref": bad}
                ).status_code,
                400,
            )
        self.assertEqual(CustomerIdentity.objects.count(), 0)

    def test_store_details_are_public_to_the_agent_and_read_only(self):
        result = self.admin_client.patch(
            "/api/console/business/",
            {"address": "台北市大安區", "phone": "02-1234-5678"},
            format="json",
        )
        self.assertEqual(result.status_code, 200, result.data)
        business = self.agent.get("/api/agent-api/business/").data
        self.assertEqual(business["address"], "台北市大安區")
        self.assertEqual(business["phone"], "02-1234-5678")
        self.assertEqual(
            self.agent.patch("/api/agent-api/business/", {"name": "bad"}).status_code, 405
        )
        self.assertEqual(self.agent.get("/api/agent-api/locations/").status_code, 404)

    def test_audit_is_read_only_paginated_and_no_profile_values(self):
        self.agent.post(
            "/api/agent-api/customer-profile/",
            {"customer_ref": A, "display_name": "Private name"},
            format="json",
        )
        result = self.owner_client.get("/api/console/audit/")
        self.assertEqual(result.status_code, 200)
        self.assertNotIn("Private name", str(result.data))
        self.assertEqual(
            self.owner_client.post("/api/console/audit/", {}, format="json").status_code,
            405,
        )
        self.assertEqual(self.owner_client.get("/api/console/audit/?page=-1").status_code, 400)
        self.assertEqual(self.agent.get("/api/console/audit/").status_code, 403)

    def test_validation_and_atomic_audit_failure(self):
        self.assertEqual(
            self.admin_client.patch(
                "/api/console/business/", {"timezone": "invalid/time"}, format="json"
            ).status_code,
            400,
        )
        with patch("core.services.audit", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                update_customer_profile(agent_actor(self.key), NEW, "Name")
        self.assertFalse(CustomerIdentity.objects.filter(agenrena_customer_ref=NEW).exists())

    def test_bootstrap_never_overwrites_existing_owner(self):
        with patch.dict(
            "os.environ",
            {
                "BOOTSTRAP_ADMIN_USERNAME": "owner",
                "BOOTSTRAP_ADMIN_PASSWORD": "different-password",
            },
        ):
            call_command("runtime_bootstrap", stdout=io.StringIO())
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password(PASSWORD))

    def test_bootstrap_initializes_owner_without_superuser(self):
        Membership.objects.all().delete()
        with patch.dict(
            "os.environ",
            {
                "BOOTSTRAP_ADMIN_USERNAME": "bootstrap",
                "BOOTSTRAP_ADMIN_PASSWORD": PASSWORD,
            },
        ):
            call_command("runtime_bootstrap", stdout=io.StringIO())
        u = get_user_model().objects.get(username="bootstrap")
        self.assertEqual(u.membership.role, "owner")
        self.assertFalse(u.is_superuser)
        self.assertTrue(u.check_password(PASSWORD))


class ConcurrentIdentityTests(TransactionTestCase):
    def test_concurrent_first_contact_has_one_identity(self):
        role = AgentRole.objects.create(code="test_role", label="Test")
        permission, _ = AgentPermission.objects.get_or_create(
            code="customer.profile.write",
            defaults={"scope": "customer", "label": "Write"},
        )
        role.permissions.add(permission)
        key, _ = AgentKey.issue("Test", role)

        def write(_):
            close_old_connections()
            try:
                return update_customer_profile(
                    agent_actor(AgentKey.objects.get(pk=key.pk)), A, "Same"
                )["id"]
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(write, range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(CustomerIdentity.objects.count(), 1)
