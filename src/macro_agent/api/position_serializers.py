"""Strict paper-position declarations and generated HTTP response contracts."""

from datetime import date
import re

from django.core.validators import RegexValidator
from rest_framework import serializers

from .serializers import (
    AuditEventSerializer, StrictIntegerField, StrictSerializer,
    StrictStringField, StrictUUIDField,
)


class DirectionField(serializers.ChoiceField):
    def __init__(self, **kwargs):
        super().__init__(choices=["long", "short"], **kwargs)

    def to_internal_value(self, data):
        if type(data) is not str:
            raise serializers.ValidationError("A string is required.")
        return super().to_internal_value(data)


class QuantityField(StrictStringField):
    """Preserve a positive fixed decimal declaration without sizing arithmetic."""

    def __init__(self, **kwargs):
        super().__init__(max_length=29, help_text=(
            "Positive fixed decimal string, at most 28 digits total and 12 fractional places. "
            "Trailing zeroes are preserved; this is a declaration, not sizing arithmetic."
        ), validators=[RegexValidator(
            r"\A(?:0|[1-9][0-9]{0,27})(?:\.[0-9]{1,12})?\Z",
        )], **kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if (not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,12})?", value)
                or len(value.replace(".", "")) > 28
                or not any(character in "123456789" for character in value)):
            raise serializers.ValidationError("A positive fixed decimal of at most 28 digits and 12 fractional places is required.")
        return value


class ExpiryField(StrictStringField):
    def __init__(self, **kwargs):
        super().__init__(min_length=10, max_length=10,
                         validators=[RegexValidator(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")], **kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        try:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError
            date.fromisoformat(value)
        except ValueError:
            raise serializers.ValidationError("A valid YYYY-MM-DD date is required.") from None
        return value


class PositionDeclarationSerializer(StrictSerializer):
    underlying = StrictStringField(max_length=128)
    direction = DirectionField()
    product_id = StrictStringField(max_length=256, allow_null=True)
    venue = StrictStringField(max_length=128, allow_null=True)
    expiry = ExpiryField(allow_null=True)
    quote_currency = StrictStringField(max_length=16, allow_null=True)
    horizon = StrictStringField(max_length=1000, allow_null=True)
    quantity = QuantityField(allow_null=True)
    quantity_unit = StrictStringField(max_length=64, allow_null=True)

    def validate(self, attrs):
        if (attrs["quantity"] is None) != (attrs["quantity_unit"] is None):
            raise serializers.ValidationError("Quantity and its unit must be supplied together or both remain null.")
        return attrs


class CreatePositionSerializer(StrictSerializer):
    command_id = StrictUUIDField()
    expected_approval_id = StrictUUIDField()
    position = PositionDeclarationSerializer()


class RevisePositionSerializer(CreatePositionSerializer):
    expected_revision = StrictIntegerField(min_value=1, max_value=2**63 - 1)


class ClosePositionSerializer(StrictSerializer):
    command_id = StrictUUIDField()
    expected_revision = StrictIntegerField(min_value=1, max_value=2**63 - 1)
    expected_approval_id = StrictUUIDField()


class PositionVersionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    position_id = serializers.UUIDField()
    parent_version_id = serializers.UUIDField(allow_null=True)
    reviewed_approval_id = serializers.UUIDField()
    paper = serializers.BooleanField()
    status = serializers.ChoiceField(choices=["open", "closed"])
    underlying = serializers.CharField(trim_whitespace=False)
    direction = serializers.ChoiceField(choices=["long", "short"])
    product_id = serializers.CharField(allow_null=True, trim_whitespace=False)
    venue = serializers.CharField(allow_null=True, trim_whitespace=False)
    expiry = serializers.CharField(allow_null=True)
    quote_currency = serializers.CharField(allow_null=True, trim_whitespace=False)
    horizon = serializers.CharField(allow_null=True, trim_whitespace=False)
    quantity = serializers.CharField(allow_null=True, trim_whitespace=False)
    quantity_unit = serializers.CharField(allow_null=True, trim_whitespace=False)
    accepted_at = serializers.DateTimeField(help_text=(
        "Protected effective command time, not a measured durable commit timestamp."
    ))
    digest = serializers.CharField()
    mapping_status = serializers.ChoiceField(choices=["user_declared_unverified"])
    missing_fields = serializers.ListField(child=serializers.CharField())


class PositionDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    thesis_id = serializers.UUIDField()
    revision = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    changed_at = serializers.DateTimeField()
    original_approval_id = serializers.UUIDField()
    current_version = PositionVersionSerializer()
    mapping_status = serializers.ChoiceField(choices=["user_declared_unverified"])
    monitoring = serializers.ChoiceField(choices=["not_configured"])


class PositionListSerializer(serializers.Serializer):
    positions = PositionDetailSerializer(many=True)
    limit = serializers.IntegerField()
    offset = serializers.IntegerField()
    has_more = serializers.BooleanField()


class PositionCommandResultSerializer(serializers.Serializer):
    position_id = serializers.UUIDField()
    version_id = serializers.UUIDField()
    revision = serializers.IntegerField()
    accepted_at = serializers.DateTimeField()


class PositionCommandSerializer(serializers.Serializer):
    command_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=["create", "revise", "close"])
    replayed = serializers.BooleanField()
    result = PositionCommandResultSerializer()
    is_current_version = serializers.BooleanField()


class PositionCommandResponseSerializer(serializers.Serializer):
    command = PositionCommandSerializer()
    position = PositionDetailSerializer()


class PositionHistorySerializer(serializers.Serializer):
    position = PositionDetailSerializer()
    versions = PositionVersionSerializer(many=True)
    audit = AuditEventSerializer(many=True)
    history_limit = serializers.IntegerField()
    truncated = serializers.BooleanField()
    replay_scope = serializers.ChoiceField(choices=["position_effective_time_history"])
