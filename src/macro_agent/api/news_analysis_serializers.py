"""Explicit news-analysis wire contracts, generated from DRF definitions."""

from django.core.validators import RegexValidator
from rest_framework import serializers

from .compilation_content_serializers import PinnedReviewCardSerializer

from .compilation_serializers import CompilationUsageSerializer, PROVIDERS
from .serializers import (
    InterpretationInputSerializer, StrictListField, StrictSerializer,
    StrictStringField, StrictUUIDField,
)


class AnalyseNextRequestSerializer(StrictSerializer):
    command_id = StrictUUIDField()
    expected_approval_id = StrictUUIDField()
    expected_exposure_digest = StrictStringField(
        min_length=64, max_length=64,
        validators=[RegexValidator(r"\A[0-9a-f]{64}\Z")],
    )
    source_id = StrictStringField(max_length=128)
    provider_id = serializers.ChoiceField(choices=PROVIDERS)
    model_id = StrictStringField(max_length=255)


class NewsCatalogSourceSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=128)
    label = serializers.CharField()
    kind = serializers.ChoiceField(choices=["rss", "fictional_fixture"])
    current_reports = serializers.IntegerField(min_value=0, help_text=(
        "Current observed heads, not unanalysed reports for a particular thesis or complete coverage."
    ))


class NewsCatalogResponseSerializer(serializers.Serializer):
    sources = NewsCatalogSourceSerializer(many=True)
    limitations = serializers.ListField(child=serializers.CharField())


class NewsContextPositionSerializer(serializers.Serializer):
    position_id = serializers.UUIDField()
    version_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=["open", "closed"])
    underlying = serializers.CharField(trim_whitespace=False)
    direction = serializers.ChoiceField(choices=["long", "short"])
    quantity = serializers.CharField(allow_null=True, trim_whitespace=False)
    quantity_unit = serializers.CharField(allow_null=True, trim_whitespace=False)
    horizon = serializers.CharField(allow_null=True, trim_whitespace=False)
    product_id = serializers.CharField(allow_null=True, trim_whitespace=False)
    venue = serializers.CharField(allow_null=True, trim_whitespace=False)
    expiry = serializers.CharField(allow_null=True)
    quote_currency = serializers.CharField(allow_null=True, trim_whitespace=False)
    missing_fields = serializers.ListField(child=serializers.CharField())
    mapping_status = serializers.ChoiceField(choices=["user_declared_unverified"])


class ApprovedNewsInterpretationSerializer(InterpretationInputSerializer):
    review_card = PinnedReviewCardSerializer(required=False, allow_null=True)


class NewsReviewContextSerializer(serializers.Serializer):
    thesis_id = serializers.UUIDField()
    approval_id = serializers.UUIDField()
    exposure_digest = serializers.CharField()
    approved_exact_text = serializers.CharField(trim_whitespace=False)
    approved_interpretation = ApprovedNewsInterpretationSerializer()
    positions = NewsContextPositionSerializer(many=True)
    limitations = serializers.ListField(child=serializers.CharField())


class NewsSourceSnapshotSerializer(serializers.Serializer):
    source_key = serializers.CharField()
    report_id = serializers.IntegerField(min_value=1)
    native_id = serializers.CharField()
    revision_id = serializers.UUIDField()
    digest = serializers.CharField()
    title = serializers.CharField(trim_whitespace=False)
    content = serializers.CharField(trim_whitespace=False, allow_blank=True)
    url = serializers.CharField(help_text="Retained attribution URL; no fetch or article-body access is implied.")
    published_at = serializers.DateTimeField(allow_null=True)
    received_at = serializers.DateTimeField()
    availability_witness_at = serializers.DateTimeField(allow_null=True, help_text=(
        "Conservative postcommit observation, not exact durable known-at or public availability."
    ))
    is_fixture = serializers.BooleanField()


class NewsApprovedThesisSerializer(serializers.Serializer):
    thesis_id = serializers.UUIDField()
    thesis_version_id = serializers.UUIDField()
    approval_id = serializers.UUIDField()
    interpretation_id = serializers.UUIDField()
    exact_text = serializers.CharField(trim_whitespace=False)
    drivers = serializers.ListField(child=serializers.CharField(trim_whitespace=False))
    horizon = serializers.CharField(allow_null=True, trim_whitespace=False)
    invalidation_signposts = serializers.ListField(child=serializers.CharField(trim_whitespace=False))
    review_card = PinnedReviewCardSerializer(required=False, allow_null=True)


class NewsAnalysisContextSerializer(serializers.Serializer):
    source = NewsSourceSnapshotSerializer()
    approved_thesis = NewsApprovedThesisSerializer()
    positions = NewsContextPositionSerializer(many=True)


class NewsAttributedFactSerializer(StrictSerializer):
    fact_id = StrictStringField(max_length=2000)
    source_revision_id = StrictUUIDField()
    field = serializers.ChoiceField(choices=["title", "content"])
    exact_quote = StrictStringField(max_length=2000)


class NewsThesisRouteSerializer(StrictSerializer):
    status = serializers.ChoiceField(choices=["potential", "review_needed", "not_identified"])
    fact_ids = StrictListField(child=StrictStringField(max_length=2000), max_length=16)
    explanation = StrictStringField(max_length=2000)


class NewsTradeRouteSerializer(NewsThesisRouteSerializer):
    position_ids = StrictListField(child=StrictUUIDField(), max_length=200)


class NewsHypothesisSerializer(StrictSerializer):
    hypothesis_id = StrictStringField(max_length=2000)
    fact_ids = StrictListField(child=StrictStringField(max_length=2000), max_length=16)
    position_ids = StrictListField(child=StrictUUIDField(), max_length=200)
    explanation = StrictStringField(max_length=2000)
    transmission = StrictStringField(max_length=2000)
    horizon = StrictStringField(max_length=2000, allow_null=True)
    assumptions = StrictListField(child=StrictStringField(max_length=2000), max_length=16)
    uncertainty = StrictStringField(max_length=2000)
    counter_case = StrictStringField(max_length=2000)
    signposts = StrictListField(child=StrictStringField(max_length=2000), max_length=16)


class NewsDocumentSerializer(StrictSerializer):
    schema_version = serializers.ChoiceField(choices=["retained-news-analysis-v1"])
    attributed_facts = NewsAttributedFactSerializer(many=True)
    thesis_route = NewsThesisRouteSerializer()
    trade_route = NewsTradeRouteSerializer()
    hypotheses = NewsHypothesisSerializer(many=True)
    trader_questions = StrictListField(child=StrictStringField(max_length=2000), max_length=16)


class NewsAnalysisSerializer(serializers.Serializer):
    id = serializers.UUIDField(allow_null=True)
    status = serializers.ChoiceField(choices=[
        "analysed", "stale", "failed", "outcome_unknown", "running", "queue_empty",
    ])
    current_disposition = serializers.ChoiceField(choices=["current", "stale", "unresolved", "queue_empty"])
    replayed = serializers.BooleanField()
    source_revision_id = serializers.UUIDField(allow_null=True)
    provider = serializers.ChoiceField(choices=PROVIDERS)
    model_id = serializers.CharField(max_length=255)
    created_at = serializers.DateTimeField(allow_null=True)
    finished_at = serializers.DateTimeField(allow_null=True)
    context = NewsAnalysisContextSerializer(allow_null=True)
    document = NewsDocumentSerializer(allow_null=True)
    usage = CompilationUsageSerializer()
    reported_cost_usd = serializers.CharField(allow_null=True)
    estimated_cost_usd = serializers.CharField(allow_null=True)
    reported_model = serializers.CharField(allow_null=True)
    provider_request_id = serializers.CharField(allow_null=True)
    latency_ms = serializers.IntegerField(min_value=0, allow_null=True)
    stop_reason = serializers.CharField(allow_null=True)
    stale_reasons = serializers.ListField(child=serializers.CharField())
    limitations = serializers.ListField(child=serializers.CharField())
    unresolved_attempt_count = serializers.IntegerField(min_value=0, help_text=(
        "Prior unresolved attempts remain visible; no unattempted report does not mean all work resolved."
    ))


class NewsAnalysisResponseSerializer(serializers.Serializer):
    analysis = NewsAnalysisSerializer()
