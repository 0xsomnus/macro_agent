"""Explicit strict input contracts and OpenAPI response descriptions."""

from rest_framework import serializers

from .strict import StrictSerializer, StrictStringField, StrictIntegerField, StrictListField, StrictUUIDField
from .compilation_content_serializers import InterpretationInputSerializer, PinnedReviewCardSerializer


class CreateThesisSerializer(StrictSerializer):
    command_id = StrictUUIDField()
    text = StrictStringField(max_length=20000)
    interpretation = InterpretationInputSerializer()


class ProposeThesisSerializer(CreateThesisSerializer):
    expected_revision = StrictIntegerField(min_value=1, max_value=2**63 - 1)


class ApproveThesisSerializer(StrictSerializer):
    command_id = StrictUUIDField()
    thesis_version_id = StrictUUIDField()
    text_digest = serializers.RegexField(r"\A[0-9a-f]{64}\Z", min_length=64, max_length=64, trim_whitespace=False)
    interpretation_version_id = StrictUUIDField()
    interpretation_digest = serializers.RegexField(r"\A[0-9a-f]{64}\Z", min_length=64, max_length=64, trim_whitespace=False)
    expected_revision = StrictIntegerField(min_value=1, max_value=2**63 - 1)

    def to_internal_value(self, data):
        if type(data) is dict:
            for name in ("text_digest", "interpretation_digest"):
                if name in data and type(data[name]) is not str:
                    raise serializers.ValidationError({name: ["A string is required."]})
        return super().to_internal_value(data)


class LoginSerializer(StrictSerializer):
    username = StrictStringField(max_length=150)
    password = StrictStringField(max_length=4096, whitespace_only=True, write_only=True)


class EmptySerializer(StrictSerializer):
    pass


class ErrorResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
    errors = serializers.JSONField(required=False)


class TextVersionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    parent_version_id = serializers.UUIDField(allow_null=True)
    exact_text = serializers.CharField(trim_whitespace=False)
    text_digest = serializers.CharField()
    created_at = serializers.DateTimeField()


class InterpretationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    text_version_id = serializers.UUIDField()
    drivers = serializers.ListField(child=serializers.CharField(trim_whitespace=False))
    horizon = serializers.CharField(allow_null=True, trim_whitespace=False)
    invalidation_signposts = serializers.ListField(child=serializers.CharField(trim_whitespace=False))
    known_at = serializers.DateTimeField(help_text=(
        "Provisional interpretation preparation time. This is not a proved durable commit timestamp "
        "and does not establish full operational known-at replay."
    ))
    digest = serializers.CharField()
    origin = serializers.ChoiceField(choices=["user_supplied", "model_compilation"])
    review_card = PinnedReviewCardSerializer(allow_null=True, required=False, help_text=(
        "Versioned exact review surface included in the interpretation hash. "
        "Labelled agent proposals remain hypotheses after review approval."
    ))


class ApprovalSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    text_version_id = serializers.UUIDField()
    interpretation_version_id = serializers.UUIDField()
    text_digest = serializers.CharField()
    interpretation_digest = serializers.CharField()
    approved_at = serializers.DateTimeField()
    digest = serializers.CharField()
    revision = serializers.IntegerField()


class DraftSerializer(serializers.Serializer):
    text_version = TextVersionSerializer()
    interpretation = InterpretationSerializer()


class ApprovedSerializer(DraftSerializer):
    approval = ApprovalSerializer()


class ThesisDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    revision = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    changed_at = serializers.DateTimeField()
    draft = DraftSerializer()
    approved = ApprovedSerializer(allow_null=True)
    monitoring = serializers.ChoiceField(choices=["not_configured"])


class ThesisListSerializer(serializers.Serializer):
    theses = ThesisDetailSerializer(many=True)
    limit = serializers.IntegerField()
    offset = serializers.IntegerField()
    has_more = serializers.BooleanField()


class CommandResultSerializer(serializers.Serializer):
    thesis_id = serializers.UUIDField()
    thesis_version_id = serializers.UUIDField()
    interpretation_version_id = serializers.UUIDField()
    approval_id = serializers.UUIDField(allow_null=True)
    revision = serializers.IntegerField()
    accepted_at = serializers.DateTimeField()


class CommandSerializer(serializers.Serializer):
    command_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=["create", "propose", "approve"])
    replayed = serializers.BooleanField()
    result = CommandResultSerializer()
    is_current_approval = serializers.BooleanField()


class ThesisCommandResponseSerializer(serializers.Serializer):
    command = CommandSerializer()
    thesis = ThesisDetailSerializer()


class AuditEventSerializer(serializers.Serializer):
    sequence = serializers.IntegerField()
    kind = serializers.CharField()
    at = serializers.DateTimeField()
    detail = serializers.JSONField()


class ThesisHistorySerializer(serializers.Serializer):
    thesis = ThesisDetailSerializer()
    text_versions = TextVersionSerializer(many=True)
    interpretations = InterpretationSerializer(many=True)
    approvals = ApprovalSerializer(many=True)
    audit = AuditEventSerializer(many=True)
    replay_scope = serializers.ChoiceField(choices=["approval_effective_time_history"])
    history_limit = serializers.IntegerField()
    truncated = serializers.BooleanField()
