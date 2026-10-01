from core.serializers import StrictInput
from django.db import transaction
from rest_framework import serializers

from . import photos
from .models import Category, MenuItem, Option, OptionGroup, OrderingSettings, Table


class StrictModelSerializer(serializers.ModelSerializer):
    def to_internal_value(self, data):
        if isinstance(data, dict):
            unknown = set(data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError({"unknown_fields": sorted(unknown)})
        return super().to_internal_value(data)


class OrderingSettingsSerializer(StrictModelSerializer):
    class Meta:
        model = OrderingSettings
        fields = [
            "currency",
            "accepts_dine_in",
            "accepts_takeout",
            "last_order_minutes_before_close",
            "agenrena_short_id",
        ]

    def validate_currency(self, value):
        if len(value) != 3 or not value.isascii() or not value.isalpha():
            raise serializers.ValidationError("請輸入三碼幣別，例如 TWD。")
        return value.upper()

    def validate_last_order_minutes_before_close(self, value):
        if value > 240:
            raise serializers.ValidationError("最多提前 240 分鐘停止接單。")
        return value

    def validate_agenrena_short_id(self, value):
        if value and not value.replace("-", "").replace("_", "").isalnum():
            raise serializers.ValidationError("請填入 Agenrena 分享連結裡的商家代碼。")
        return value


class CategorySerializer(StrictModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "sort_order", "is_active"]


class PhotoInput(StrictInput):
    id = serializers.UUIDField(required=False)
    upload = serializers.CharField(required=False, max_length=40)
    focal_x = serializers.IntegerField(min_value=0, max_value=100, default=50)
    focal_y = serializers.IntegerField(min_value=0, max_value=100, default=50)

    def validate(self, attrs):
        if ("id" in attrs) == ("upload" in attrs):
            raise serializers.ValidationError("請選擇現有照片或上傳新照片。")
        return attrs


class MenuItemSerializer(StrictModelSerializer):
    photos = PhotoInput(many=True, required=False, max_length=photos.MAX_PHOTOS)

    def validate_photos(self, rows):
        known = set(self.instance.photos.values_list("id", flat=True)) if self.instance else set()
        ids = [r["id"] for r in rows if "id" in r]
        uploads = [r["upload"] for r in rows if "upload" in r]
        if len(ids) != len(set(ids)) or not set(ids) <= known:
            raise serializers.ValidationError("照片已變更，請重新整理後再試。")
        if len(uploads) != len(set(uploads)):
            raise serializers.ValidationError("同一張上傳照片不能重複使用。")
        files = self.context["request"].FILES
        for row in rows:
            if "upload" in row:
                file = files.get(row["upload"])
                if file is None:
                    raise serializers.ValidationError("找不到上傳照片，請重新選擇。")
                row["prepared"] = photos.prepare(file)
        return rows

    def create(self, validated_data):
        rows = validated_data.pop("photos", [])
        item = super().create(validated_data)
        photos.sync(item, rows, self.photo_writes)
        return item

    def update(self, item, validated_data):
        rows = validated_data.pop("photos", None)
        item = super().update(item, validated_data)
        if rows is not None:
            photos.sync(item, rows, self.photo_writes)
        return item

    def to_representation(self, item):
        # PhotoInput is a write contract; publish only generated URLs on reads.
        data = super().to_representation(item)
        data["photos"] = [photos.payload(p) for p in item.photos.all()]
        return data

    class Meta:
        model = MenuItem
        fields = [
            "id",
            "category",
            "name",
            "description",
            "price",
            "availability",
            "guidance",
            "sort_order",
            "is_active",
            "option_groups",
            "photos",
        ]

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("價格不能小於 0。")
        return value


class OptionInput(StrictInput):
    id = serializers.UUIDField(required=False)
    name = serializers.CharField(max_length=60)
    price_delta = serializers.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_available = serializers.BooleanField(default=True)


class OptionGroupSerializer(StrictModelSerializer):
    """A group and its choices, saved together: the list order is the display
    order, missing choices are removed, choices with an id are updated."""

    options = OptionInput(many=True)

    class Meta:
        model = OptionGroup
        fields = ["id", "name", "min_select", "max_select", "sort_order", "options"]

    def validate(self, attrs):
        options = attrs.get("options", None)
        instance = self.instance
        count = len(options) if options is not None else instance.options.count()
        low = attrs.get("min_select", instance.min_select if instance else 0)
        high = attrs.get("max_select", instance.max_select if instance else 1)
        if count == 0:
            raise serializers.ValidationError("至少要有一個選項。")
        if high < 1 or low > high or high > count:
            raise serializers.ValidationError(
                "選擇數量需滿足 0 ≤ 最少 ≤ 最多 ≤ 選項數，且最多至少 1。"
            )
        if options is not None:
            names = [o["name"].strip() for o in options]
            if len(set(names)) != len(names):
                raise serializers.ValidationError("同一群組的選項名稱不能重複。")
            ids = [o["id"] for o in options if "id" in o]
            known = set(instance.options.values_list("id", flat=True)) if instance else set()
            if len(set(ids)) != len(ids) or not set(ids) <= known:
                raise serializers.ValidationError("選項已變更，請重新整理後再試。")
        return attrs

    def to_representation(self, group):
        data = super().to_representation(group)
        data["options"] = [
            {
                "id": str(o.pk),
                "name": o.name,
                "price_delta": f"{o.price_delta:.2f}",
                "is_available": o.is_available,
            }
            for o in group.options.all()
        ]
        return data

    @transaction.atomic
    def create(self, validated_data):
        options = validated_data.pop("options")
        group = OptionGroup.objects.create(**validated_data)
        self._sync(group, options)
        return group

    @transaction.atomic
    def update(self, group, validated_data):
        options = validated_data.pop("options", None)
        group = super().update(group, validated_data)
        if options is not None:
            self._sync(group, options)
        return group

    def _sync(self, group, options):
        keep = [o["id"] for o in options if "id" in o]
        # Past orders keep their own copy of names and prices.
        group.options.exclude(pk__in=keep).delete()
        for index, data in enumerate(options):
            # Partial updates carry only what changed; new choices take defaults.
            fields = {"name": data["name"].strip(), "sort_order": index}
            fields |= {k: data[k] for k in ("price_delta", "is_available") if k in data}
            if "id" in data:
                Option.objects.filter(pk=data["id"], group=group).update(**fields)
            else:
                Option.objects.create(group=group, **fields)


class OptionAvailabilitySerializer(StrictModelSerializer):
    class Meta:
        model = Option
        fields = ["id", "is_available"]


class PauseInput(StrictInput):
    action = serializers.ChoiceField(choices=["pause", "resume"])
    minutes = serializers.IntegerField(required=False, allow_null=True, default=None)
    reason = serializers.CharField(max_length=120, allow_blank=True, default="")


class TableSerializer(StrictModelSerializer):
    class Meta:
        model = Table
        fields = ["id", "code", "is_active"]


class TakeoutInput(StrictInput):
    phone = serializers.JSONField(required=False)
    items = serializers.JSONField()
    note = serializers.JSONField(required=False)


class RoundInput(StrictInput):
    items = serializers.JSONField()
    note = serializers.JSONField(required=False)


class ConfirmDraftInput(StrictInput):
    phone = serializers.JSONField(required=False)
    items = serializers.JSONField(required=False)
    note = serializers.JSONField(required=False)


class DraftInput(StrictInput):
    customer_ref = serializers.CharField(max_length=36)
    items = serializers.JSONField()
    customer_name = serializers.JSONField(required=False)
    note = serializers.JSONField(required=False)


class AmendInput(StrictInput):
    items = serializers.JSONField()
    confirm = serializers.BooleanField(default=False)


class RejectInput(StrictInput):
    message = serializers.CharField(max_length=500, allow_blank=True, default="")
