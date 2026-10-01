from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import AgentRole, Business
from .permissions import CUSTOMER_REF


class StrictInput(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("請提供 JSON object。")
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({"unknown_fields": sorted(unknown)})
        return super().to_internal_value(data)


class BusinessSerializer(serializers.ModelSerializer):
    class Meta:
        model = Business
        fields = ["name", "about", "address", "phone", "timezone"]


class ConsoleBusinessSerializer(BusinessSerializer):
    class Meta(BusinessSerializer.Meta):
        fields = ["software_name", *BusinessSerializer.Meta.fields]


class LoginInput(StrictInput):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=1024, trim_whitespace=False)


class MemberCreateInput(StrictInput):
    username = serializers.RegexField(
        r"^[\w.@+-]+$",
        max_length=150,
        validators=[UniqueValidator(queryset=get_user_model().objects.all())],
    )
    name = serializers.CharField(max_length=150, allow_blank=True, default="")
    password = serializers.CharField(max_length=1024, trim_whitespace=False)
    role = serializers.ChoiceField(choices=["owner", "admin"], default="admin")


class MemberUpdateInput(StrictInput):
    name = serializers.CharField(max_length=150, allow_blank=True, required=False)
    role = serializers.ChoiceField(choices=["owner", "admin"], required=False)
    is_active = serializers.BooleanField(required=False)


class PasswordInput(StrictInput):
    old_password = serializers.CharField(max_length=1024, trim_whitespace=False)
    password = serializers.CharField(max_length=1024, trim_whitespace=False)


class KeyInput(StrictInput):
    label = serializers.CharField(max_length=80)
    role = serializers.PrimaryKeyRelatedField(queryset=AgentRole.objects.all())


class CustomerRefInput(StrictInput):
    customer_ref = serializers.RegexField(rf"^{CUSTOMER_REF}$", max_length=36)


class ProfileInput(CustomerRefInput):
    display_name = serializers.CharField(max_length=120)
