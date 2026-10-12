"""Strict publication commands and explicit retained/public-current envelopes."""

from django.core.validators import RegexValidator
from rest_framework import serializers
from .synthesis_serializers import SynthesisResponseSerializer

from .desk_serializers import DailyReviewDispositionSerializer, RetainedDailyReviewSerializer
from .strict import StrictIntegerField, StrictSerializer, StrictStringField, StrictUUIDField


class PublishDailyReviewSerializer(StrictSerializer):
    command_id = StrictUUIDField()
    expected_review_digest = StrictStringField(min_length=64, max_length=64,
        validators=[RegexValidator(r"\A[0-9a-f]{64}\Z")])
    expected_generation = StrictIntegerField(min_value=0, max_value=2**63 - 1)
    fanout_limit = StrictIntegerField(min_value=1, max_value=1000)


class DailyPublicationDecisionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["current", "superseded"])
    reasons = serializers.ListField(child=serializers.CharField())
    reassessment_required = serializers.BooleanField()


class RetainedDailyPublicationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    command_id = serializers.UUIDField()
    review_id = serializers.UUIDField()
    brief_id = serializers.CharField()
    assessment_id = serializers.CharField()
    review_digest = serializers.CharField(min_length=64, max_length=64)
    expected_generation = serializers.IntegerField(min_value=0)
    published_at = serializers.DateTimeField(help_text=(
        "Clock sampled after publication protection. This is not an exact durable commit or delivery time."
    ))
    original_decision = DailyPublicationDecisionSerializer()
    generation_at_publication = serializers.IntegerField(min_value=1, allow_null=True)


class DailyPublicationDispositionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["current", "superseded"])
    reasons = serializers.ListField(child=serializers.CharField())
    observed_at = serializers.DateTimeField()


class DailyPublicationIntentSerializer(serializers.Serializer):
    id = serializers.CharField()
    state = serializers.ChoiceField(choices=["pending", "delivered", "canceled"])


class DailyPublicationDetailSerializer(serializers.Serializer):
    publication = RetainedDailyPublicationSerializer()
    current_disposition = DailyPublicationDispositionSerializer()
    notification_intent = DailyPublicationIntentSerializer(allow_null=True, help_text=(
        "Internal atomic notification intent, including its present cancellation state. No external delivery is enabled."
    ))
    replayed = serializers.BooleanField()
    review = RetainedDailyReviewSerializer()


class CurrentDailyBriefSerializer(serializers.Serializer):
    thesis_id = serializers.UUIDField()
    brief_id = serializers.CharField(allow_null=True)
    generation = serializers.IntegerField(min_value=0)
    current_publication = DailyPublicationDetailSerializer(allow_null=True, help_text=(
        "Only the protected current pointer. Null does not fall back to the latest historical review."
    ))
    observed_at = serializers.DateTimeField()

    current_synthesis = SynthesisResponseSerializer(allow_null=True, help_text=(
        "Successful current interpretation of this exact published review. No historical fallback or publication authority."
    ))


class DailyPublicationPreviewSerializer(serializers.Serializer):
    review_id = serializers.UUIDField()
    review_digest = serializers.CharField(min_length=64, max_length=64)
    thesis_id = serializers.UUIDField()
    brief_id = serializers.CharField()
    expected_generation = serializers.IntegerField(min_value=0)
    fanout_limit = serializers.IntegerField(min_value=1, max_value=1000)
    current_disposition = DailyReviewDispositionSerializer()
