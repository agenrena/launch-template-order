"""Photo validation and storage. Only re-encoded pixels are published."""

import logging
import warnings
from io import BytesIO
from uuid import uuid4

from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework import serializers

from .models import MenuPhoto

logger = logging.getLogger(__name__)
MAX_PHOTOS = 12
MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 24_000_000


def prepare(upload):
    if upload.size > MAX_BYTES:
        raise serializers.ValidationError("每張照片最多 10 MB。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(upload) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise serializers.ValidationError("請上傳 JPEG、PNG 或 WebP 照片。")
                if source.width * source.height > MAX_PIXELS:
                    raise serializers.ValidationError("照片最多 2400 萬像素，請縮小後再上傳。")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                full = encode(image)
                image.thumbnail((480, 480), Image.Resampling.LANCZOS)
                return full, encode(image)
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise serializers.ValidationError("無法讀取照片，請重新選擇 JPEG、PNG 或 WebP。") from exc


def encode(image):
    # A fresh image strips EXIF (including GPS), comments and embedded profiles.
    clean = Image.new("RGB", image.size)
    clean.paste(image)
    output = BytesIO()
    clean.save(output, "WEBP", quality=85, method=4)
    return output.getvalue()


def payload(photo):
    base = f"/api/web/menu-photos/{photo.pk}"
    return {
        "id": str(photo.pk),
        "url": base + "/image/",
        "thumbnail_url": base + "/thumbnail/",
        "focal_x": photo.focal_x,
        "focal_y": photo.focal_y,
    }


def delete_files(files):
    for storage, name in files:
        try:
            storage.delete(name)
        except OSError:
            logger.warning("Could not remove a menu photo file; storage cleanup required.")


def sync(item, rows, written):
    """Called within save_catalog's transaction; removed files wait for commit."""
    existing = {str(p.pk): p for p in item.photos.all()}
    keep = {str(r["id"]) for r in rows if "id" in r}
    if not keep <= existing.keys():
        raise serializers.ValidationError("照片已變更，請重新整理後再試。")
    removed = [p for key, p in existing.items() if key not in keep]
    for index, row in enumerate(rows):
        photo = existing[str(row["id"])] if "id" in row else MenuPhoto(item=item)
        if "prepared" in row:
            for field, data in zip((photo.image, photo.thumbnail), row["prepared"], strict=True):
                field.save(f"{uuid4().hex}.webp", ContentFile(data), save=False)
                written.append((field.storage, field.name))
        photo.sort_order = index
        photo.focal_x = row.get("focal_x", photo.focal_x)
        photo.focal_y = row.get("focal_y", photo.focal_y)
        photo.save()
    files = [(f.storage, f.name) for p in removed for f in (p.image, p.thumbnail)]
    item.photos.filter(pk__in=[p.pk for p in removed]).delete()
    transaction.on_commit(lambda: delete_files(files))
    # The serializer may have received a prefetched instance.
    item._prefetched_objects_cache = {}
