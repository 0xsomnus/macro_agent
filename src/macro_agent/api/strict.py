"""Shared strict DRF fields and schema behavior for explicit wire contracts."""

import uuid

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.extensions import OpenApiSerializerExtension
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if type(data) is not dict:
            raise serializers.ValidationError({"non_field_errors": ["A JSON object is required."]})
        if set(data) - set(self.fields):
            raise serializers.ValidationError({"non_field_errors": ["Unknown fields are not accepted."]})
        return super().to_internal_value(data)


class StrictSerializerSchemaExtension(OpenApiSerializerExtension):
    target_class = "macro_agent.api.strict.StrictSerializer"
    match_subclasses = True

    def map_serializer(self, auto_schema, direction):
        schema = auto_schema._map_serializer(self.target, direction, bypass_extensions=True)
        schema["additionalProperties"] = False
        return schema


class StrictStringField(serializers.CharField):
    def __init__(self, *args, whitespace_only=False, **kwargs):
        self.whitespace_only = whitespace_only
        kwargs["trim_whitespace"] = False
        super().__init__(*args, **kwargs)

    def to_internal_value(self, data):
        if type(data) is not str:
            raise serializers.ValidationError("A string is required.")
        if "\x00" in data:
            raise serializers.ValidationError("NUL is not accepted.")
        try:
            data.encode("utf-8", errors="strict")
        except UnicodeError:
            raise serializers.ValidationError("Valid Unicode is required.") from None
        if not self.whitespace_only and not data.strip():
            raise serializers.ValidationError("A nonblank string is required.")
        return super().to_internal_value(data)


@extend_schema_field(OpenApiTypes.UUID)
class StrictUUIDField(StrictStringField):
    def __init__(self, **kwargs):
        super().__init__(max_length=36, **kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        try:
            if str(uuid.UUID(value)) != value:
                raise ValueError
        except (ValueError, AttributeError):
            raise serializers.ValidationError("A canonical UUID string is required.") from None
        return value


class StrictIntegerField(serializers.IntegerField):
    def to_internal_value(self, data):
        if type(data) is not int:
            raise serializers.ValidationError("An integer is required.")
        return super().to_internal_value(data)


class StrictListField(serializers.ListField):
    def to_internal_value(self, data):
        if type(data) is not list:
            raise serializers.ValidationError("An array is required.")
        return super().to_internal_value(data)
