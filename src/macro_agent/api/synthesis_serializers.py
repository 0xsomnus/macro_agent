"""Fresh interpretation contracts, separate from the retained digest authority."""

from rest_framework import serializers
from .strict import StrictSerializer, StrictUUIDField, StrictStringField, StrictListField
from .compilation_serializers import CompilationUsageSerializer, PROVIDERS


class SynthesizeReviewSerializer(StrictSerializer):
    command_id = StrictUUIDField()
    expected_review_digest = StrictStringField(min_length=64, max_length=64)
    provider_id = serializers.ChoiceField(choices=PROVIDERS)
    model_id = StrictStringField(max_length=255)


class SynthesisClaimSerializer(StrictSerializer):
    claim_id = StrictStringField(max_length=128)
    source_revision_id = StrictUUIDField()
    source_field = serializers.ChoiceField(choices=["title", "content"])
    quote = StrictStringField(max_length=2000)


class SynthesisSectionSerializer(StrictSerializer):
    text = StrictStringField(max_length=2000)
    claim_ids = StrictListField(child=StrictStringField(max_length=128), max_length=32)
    prior_analysis_ids = StrictListField(child=StrictUUIDField(), max_length=32)
    uncertainty = StrictStringField(max_length=2000)


class SynthesisThesisEffectSerializer(StrictSerializer):
    effect = serializers.ChoiceField(choices=["supports", "challenges", "mixed", "unresolved"])
    reasoning = StrictStringField(max_length=2000)
    claim_ids = StrictListField(child=StrictStringField(max_length=128), max_length=32)
    prior_analysis_ids = StrictListField(child=StrictUUIDField(), max_length=32)
    uncertainty = StrictStringField(max_length=2000)


class SynthesisTradeEffectSerializer(SynthesisThesisEffectSerializer):
    position_id = StrictUUIDField()
    effect = serializers.ChoiceField(choices=["potential_risk", "potential_opportunity", "mixed", "unresolved"])


class SynthesisDocumentSerializer(StrictSerializer):
    schema_version = serializers.ChoiceField(choices=["retained-daily-synthesis-v1"])
    attributed_claims = SynthesisClaimSerializer(many=True, max_length=32)
    overview = SynthesisSectionSerializer()
    thesis_effect = SynthesisThesisEffectSerializer()
    trade_effects = SynthesisTradeEffectSerializer(many=True, max_length=200)
    counter_case = SynthesisSectionSerializer()
    watch_questions = StrictListField(child=StrictStringField(max_length=2000), max_length=32)
    gaps = StrictListField(child=StrictStringField(max_length=2000), max_length=32)


class SynthesisContextSerializer(serializers.Serializer):
    review_id = serializers.UUIDField()
    review_digest = serializers.CharField(min_length=64, max_length=64)
    review = serializers.JSONField(help_text="Exact immutable daily digest, validated by the retained daily-review domain contract.")
    original_inputs = serializers.JSONField(help_text="Exact approved inputs and full attached paper book, not current substitutes.")
    report_heads = serializers.DictField(child=serializers.UUIDField(allow_null=True), help_text="Original report head labels distinguish historical revisions.")


class SynthesisSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    command_id = serializers.UUIDField()
    review_id = serializers.UUIDField()
    review_digest = serializers.CharField(min_length=64, max_length=64)
    provider = serializers.ChoiceField(choices=PROVIDERS)
    model_id = serializers.CharField()
    schema_version = serializers.CharField()
    prompt_version = serializers.CharField()
    status = serializers.ChoiceField(choices=["synthesised", "stale", "failed", "outcome_unknown", "running"])
    created_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField(allow_null=True)
    document = SynthesisDocumentSerializer(allow_null=True)
    context = SynthesisContextSerializer()
    context_digest = serializers.CharField(min_length=64, max_length=64)
    usage = CompilationUsageSerializer()
    reported_cost_usd = serializers.CharField(allow_null=True)
    estimated_cost_usd = serializers.CharField(allow_null=True)
    reported_model = serializers.CharField(allow_null=True)
    provider_request_id = serializers.CharField(allow_null=True)
    latency_ms = serializers.IntegerField(min_value=0, allow_null=True)
    stop_reason = serializers.CharField(allow_null=True)
    original_stale_reasons = serializers.ListField(child=serializers.CharField())
    limitations = serializers.ListField(child=serializers.CharField())


class SynthesisDispositionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["current", "stale", "unresolved"])
    stale_reasons = serializers.ListField(child=serializers.CharField())
    observed_at = serializers.DateTimeField()
    publication_authority = serializers.ChoiceField(choices=[False])


class SynthesisResponseSerializer(serializers.Serializer):
    synthesis = SynthesisSerializer()
    current_disposition = SynthesisDispositionSerializer()
    replayed = serializers.BooleanField()
    review_id = serializers.UUIDField()
    review_digest = serializers.CharField(min_length=64, max_length=64)
