"""Explicit publication authority for retained driver news, separate from inference."""

from rest_framework import serializers
from .daily_publication_serializers import (
    DailyPublicationDecisionSerializer, DailyPublicationDispositionSerializer,
    DailyPublicationIntentSerializer,
)
from .news_analysis_serializers import NewsAnalysisSerializer
from .strict import StrictIntegerField, StrictSerializer, StrictStringField, StrictUUIDField


POLICY = "evidence-linked-driver-review-v1"


class PublishNewsSerializer(StrictSerializer):
    command_id = StrictUUIDField()
    expected_analysis_digest = StrictStringField(min_length=64, max_length=64)
    expected_generation = StrictIntegerField(min_value=0, max_value=2**63 - 1)
    fanout_limit = StrictIntegerField(min_value=1, max_value=1000)
    policy_version = serializers.ChoiceField(choices=[POLICY])


class NewsAttentionDecisionSerializer(serializers.Serializer):
    policy_version = serializers.ChoiceField(choices=[POLICY])
    status = serializers.ChoiceField(choices=[
        "not_requested", "unmapped", "unlinked", "duplicate", "unchanged", "review_requested", "review_carried", "superseded",
    ])
    reason = serializers.CharField()
    signal_digest = serializers.CharField(min_length=64, max_length=64, allow_null=True)
    kind = serializers.ChoiceField(choices=["qualified_driver_review"])


class RetainedNewsPublicationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    command_id = serializers.UUIDField()
    analysis_id = serializers.UUIDField()
    analysis_digest = serializers.CharField(min_length=64, max_length=64)
    brief_id = serializers.CharField()
    assessment_id = serializers.CharField()
    expected_generation = serializers.IntegerField(min_value=0)
    published_at = serializers.DateTimeField()
    original_decision = DailyPublicationDecisionSerializer()
    generation_at_publication = serializers.IntegerField(min_value=1, allow_null=True)
    attention_decision = NewsAttentionDecisionSerializer()
    predecessor_publication_id = serializers.UUIDField(allow_null=True)
    attention_origin_publication_id = serializers.UUIDField(allow_null=True)
    slot_lease_token = serializers.UUIDField(allow_null=True)


class NewsPublicationDetailSerializer(serializers.Serializer):
    publication = RetainedNewsPublicationSerializer()
    current_disposition = DailyPublicationDispositionSerializer()
    notification_intent = DailyPublicationIntentSerializer(allow_null=True)
    analysis = NewsAnalysisSerializer()
    replayed = serializers.BooleanField()


class NewsPublicationPreviewDispositionSerializer(serializers.Serializer):
    stale_reasons = serializers.ListField(child=serializers.CharField())
    observed_at = serializers.DateTimeField()


class NewsPublicationPreviewSerializer(serializers.Serializer):
    analysis_id = serializers.UUIDField()
    analysis_digest = serializers.CharField(min_length=64, max_length=64)
    thesis_id = serializers.UUIDField()
    brief_id = serializers.CharField()
    expected_generation = serializers.IntegerField(min_value=0)
    fanout_limit = serializers.IntegerField(min_value=1, max_value=1000)
    policy_version = serializers.ChoiceField(choices=[POLICY])
    current_disposition = NewsPublicationPreviewDispositionSerializer()


class CurrentNewsBriefSerializer(serializers.Serializer):
    thesis_id = serializers.UUIDField()
    brief_id = serializers.CharField(allow_null=True)
    generation = serializers.IntegerField(min_value=0)
    current_publication = NewsPublicationDetailSerializer(allow_null=True)
    observed_at = serializers.DateTimeField()
