"""Real multipart uploads, public delivery, ownership and atomic photo edits."""

import json
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from core.models import AgentKey, AgentRole, AuditEvent, Membership
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from ordering.models import Category, MenuItem, MenuPhoto


def picture(name="dish.jpg", color="red", size=(1800, 900)):
    data = BytesIO()
    image = Image.new("RGB", size, color)
    exif = Image.Exif()
    exif[270] = "private camera comment"
    image.save(data, "JPEG", exif=exif)
    return SimpleUploadedFile(name, data.getvalue(), content_type="image/jpeg")


class MenuPhotoTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.directory.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        owner = get_user_model().objects.create_user(username="photo_owner")
        Membership.objects.create(user=owner, role="owner")
        self.console = APIClient()
        self.console.force_login(owner)
        self.web = APIClient()
        self.category = Category.objects.create(name="主餐")
        self.item = MenuItem.objects.create(category=self.category, name="飯", price=80)
        self.path = f"/api/console/menu-items/{self.item.pk}/"

    def upload(self, rows=None, **extra):
        return self.console.patch(
            self.path,
            {
                "payload": json.dumps(
                    {"photos": rows or [{"upload": "first"}, {"upload": "second"}], **extra}
                ),
                "first": picture(),
                "second": picture("second.jpg", "blue"),
            },
            format="multipart",
        )

    def test_batch_upload_resize_strip_metadata_and_public_delivery(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200, response.data)
        photos = response.data["photos"]
        self.assertEqual(len(photos), 2)
        public = self.web.get("/api/web/store/").data["menu"][0]["items"][0]["photos"]
        self.assertEqual(public, photos)
        for variant, size in [("url", (1600, 800)), ("thumbnail_url", (480, 240))]:
            response = self.web.get(photos[0][variant])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/webp")
            image = Image.open(BytesIO(b"".join(response.streaming_content)))
            self.assertEqual(image.size, size)
            self.assertEqual(dict(image.getexif()), {})
        self.assertTrue(AuditEvent.objects.filter(action="menuitem.updated").exists())
        self.assertEqual(self.web.post(photos[0]["url"], {}).status_code, 405)
        self.assertEqual(
            self.web.get(photos[0]["url"].replace("/image/", "/original/")).status_code, 404
        )

    def test_create_dish_and_photos_together(self):
        response = self.console.post(
            "/api/console/menu-items/",
            {
                "payload": json.dumps(
                    {
                        "category": str(self.category.pk),
                        "name": "麵",
                        "price": "90",
                        "photos": [{"upload": "first"}],
                    }
                ),
                "first": picture(),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(response.data["photos"]), 1)

    def test_reorder_crop_remove_and_clear(self):
        first, second = self.upload().data["photos"]
        response = self.console.patch(
            self.path,
            {
                "photos": [
                    {"id": second["id"], "focal_x": 0, "focal_y": 100},
                    {"id": first["id"]},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([p["id"] for p in response.data["photos"]], [second["id"], first["id"]])
        self.assertEqual(response.data["photos"][0]["focal_x"], 0)
        # A sold-out toggle must leave the album intact.
        response = self.console.patch(self.path, {"availability": "sold_out"}, format="json")
        self.assertEqual(len(response.data["photos"]), 2)
        old = MenuPhoto.objects.get(pk=first["id"])
        with self.captureOnCommitCallbacks(execute=True):
            response = self.console.patch(
                self.path, {"photos": [{"id": second["id"]}]}, format="json"
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(old.image.storage.exists(old.image.name))
        self.assertEqual(self.web.get(first["url"]).status_code, 404)
        with self.captureOnCommitCallbacks(execute=True):
            self.console.patch(self.path, {"photos": []}, format="json")
        self.assertEqual(list(Path(self.directory.name).rglob("*.webp")), [])
        self.assertEqual(MenuPhoto.objects.count(), 0)

    def test_foreign_duplicate_missing_and_invalid_crop_are_rejected(self):
        first = self.upload().data["photos"][0]
        other = MenuItem.objects.create(category=self.category, name="別道菜")
        foreign = self.console.patch(
            f"/api/console/menu-items/{other.pk}/", {"photos": [{"id": first["id"]}]}, format="json"
        )
        self.assertEqual(foreign.status_code, 400)
        for rows in [
            [{"id": first["id"]}, {"id": first["id"]}],
            [{"upload": "missing"}],
            [{"id": first["id"], "focal_x": 101}],
            [{"id": first["id"], "upload": "first"}],
            [{}],
            [{"upload": str(i)} for i in range(13)],
        ]:
            response = self.console.patch(self.path, {"photos": rows}, format="json")
            self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.item.photos.count(), 2)

    def test_invalid_image_batch_does_not_save_any_part_of_edit(self):
        response = self.console.patch(
            self.path,
            {
                "payload": json.dumps(
                    {"name": "不應儲存", "photos": [{"upload": "first"}, {"upload": "bad"}]}
                ),
                "first": picture(),
                "bad": SimpleUploadedFile("pretend.jpg", b"<svg>not an image</svg>", "image/jpeg"),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.item.refresh_from_db()
        self.assertEqual(self.item.name, "飯")
        self.assertEqual(self.item.photos.count(), 0)
        self.assertEqual(list(Path(self.directory.name).rglob("*.webp")), [])

    def test_storage_or_audit_failure_rolls_back_and_cleans_new_files(self):
        first = self.upload().data["photos"][0]
        files_before = set(Path(self.directory.name).rglob("*.webp"))
        with patch("ordering.services.audit", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(RuntimeError):
                self.upload(rows=[{"upload": "first"}], name="不應儲存")
        self.item.refresh_from_db()
        self.assertEqual(self.item.name, "飯")
        self.assertEqual(self.item.photos.count(), 2)
        self.assertEqual(set(Path(self.directory.name).rglob("*.webp")), files_before)
        self.assertTrue(MenuPhoto.objects.filter(pk=first["id"]).exists())

    def test_permissions_and_csrf_protect_upload(self):
        self.assertEqual(self.web.patch(self.path, {"photos": []}, format="json").status_code, 403)
        _, secret = AgentKey.issue("photo agent", AgentRole.objects.get(pk="customer_service"))
        agent = APIClient()
        agent.credentials(HTTP_AUTHORIZATION="Bearer " + secret)
        self.assertEqual(agent.patch(self.path, {"photos": []}, format="json").status_code, 403)
        csrf = APIClient(enforce_csrf_checks=True)
        csrf.force_login(get_user_model().objects.get(username="photo_owner"))
        self.assertEqual(csrf.patch(self.path, {"photos": []}, format="json").status_code, 403)

    def test_image_byte_and_pixel_limits(self):
        from rest_framework.exceptions import ValidationError

        from ordering.photos import prepare

        file = picture()
        file.size = 10 * 1024 * 1024 + 1
        with self.assertRaises(ValidationError):
            prepare(file)
        with patch("ordering.photos.MAX_PIXELS", 100):
            with self.assertRaises(ValidationError):
                prepare(picture(size=(20, 20)))

    def test_exif_rotation_and_transparent_png(self):
        from ordering.photos import prepare

        data = BytesIO()
        image = Image.new("RGB", (40, 20), "red")
        exif = Image.Exif()
        exif[274] = 6
        image.save(data, "JPEG", exif=exif)
        full, _ = prepare(SimpleUploadedFile("rotated.jpg", data.getvalue()))
        self.assertEqual(Image.open(BytesIO(full)).size, (20, 40))
        data = BytesIO()
        Image.new("RGBA", (30, 20), (255, 0, 0, 100)).save(data, "PNG")
        full, _ = prepare(SimpleUploadedFile("transparent.png", data.getvalue()))
        self.assertEqual(Image.open(BytesIO(full)).format, "WEBP")
