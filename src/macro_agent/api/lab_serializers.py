"""Strict local recorded-news request and reviewable response shape."""

from rest_framework import serializers

from .serializers import StrictSerializer, StrictUUIDField


class RecordedNewsRequestSerializer(StrictSerializer):
    expected_approval_id = StrictUUIDField()


class RecordedBriefSerializer(serializers.Serializer):
    id = serializers.CharField()
    generation = serializers.IntegerField()
    context_status = serializers.ChoiceField(choices=["ready"])
    current_assessment_id = serializers.CharField()
    input_observed_at = serializers.DateTimeField()
    commit_time_measured = serializers.BooleanField()


class RecordedFactSerializer(serializers.Serializer):
    field = serializers.CharField()
    value = serializers.JSONField()


class RecordedNotificationSerializer(serializers.Serializer):
    intent_id = serializers.CharField()
    state = serializers.ChoiceField(choices=["pending", "canceled", "delivered"])
    external_delivery = serializers.CharField(help_text='Always "not_configured" for recorded examples.')


class RecordedNoticeSerializer(serializers.Serializer):
    assessment_id = serializers.CharField()
    kind = serializers.ChoiceField(choices=["supported_factual_notice"])
    is_current = serializers.BooleanField()
    replayed = serializers.BooleanField()
    portfolio_impact = serializers.ChoiceField(choices=["unresolved"])
    expectations = serializers.ChoiceField(choices=["unavailable"])
    facts = RecordedFactSerializer(many=True)
    notification = RecordedNotificationSerializer()


class RecordedSourceSerializer(serializers.Serializer):
    event_id = serializers.CharField()
    revision = serializers.IntegerField()
    source_id = serializers.CharField()
    synthetic = serializers.BooleanField()
    public_available_at = serializers.DateTimeField()
    recorded_system_received_at = serializers.DateTimeField()
    recorded_known_at = serializers.DateTimeField()


class RecordedScreeningSerializer(serializers.Serializer):
    basis = serializers.ChoiceField(choices=["recorded_fixture"])
    route = serializers.ChoiceField(choices=["investigate"])
    reasons = serializers.ListField(child=serializers.CharField())
    personalized_relevance = serializers.CharField(help_text='Always "unresolved"; no personalized analysis was performed.')


class RecordedPositionSerializer(serializers.Serializer):
    position_id = serializers.UUIDField()
    version_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=["open", "closed"])
    underlying = serializers.CharField(trim_whitespace=False)
    direction = serializers.ChoiceField(choices=["long", "short"])
    quantity = serializers.CharField(allow_null=True, trim_whitespace=False)
    quantity_unit = serializers.CharField(allow_null=True, trim_whitespace=False)
    horizon = serializers.CharField(allow_null=True, trim_whitespace=False)
    mapping_status = serializers.ChoiceField(choices=["user_declared_unverified"])
    missing_fields = serializers.ListField(child=serializers.CharField())


class RecordedNewsResponseSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=["recorded_example"])
    synthetic = serializers.BooleanField()
    monitoring = serializers.ChoiceField(choices=["not_configured"])
    model = serializers.ChoiceField(choices=["not_used"])
    provider_calls = serializers.IntegerField()
    provider_spend = serializers.IntegerField()
    thesis_id = serializers.UUIDField()
    snapshot_at = serializers.DateTimeField(help_text="Protected currentness snapshot, not an admission commit timestamp.")
    brief = RecordedBriefSerializer()
    notice = RecordedNoticeSerializer()
    source = RecordedSourceSerializer()
    screening = RecordedScreeningSerializer()
    positions = RecordedPositionSerializer(many=True)
    limitations = serializers.ListField(child=serializers.CharField())
