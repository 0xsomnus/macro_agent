"""Explicit internal compilation requests and generated response descriptions."""

from rest_framework import serializers

from .serializers import (
    InterpretationInputSerializer, StrictIntegerField, StrictListField,
    StrictSerializer, StrictStringField, StrictUUIDField, ThesisDetailSerializer,
)


PROVIDERS = ("nanogpt", "openrouter", "cheaperinference")


class CompileThesisRequestSerializer(StrictSerializer):
    command_id = StrictUUIDField()
    expected_revision = StrictIntegerField(min_value=1, max_value=2**63 - 1)
    provider_id = serializers.ChoiceField(choices=PROVIDERS, help_text=(
        "Provider identity shown by the catalogue, pinned against backend configuration."
    ))
    model_id = StrictStringField(max_length=255, help_text=(
        "Explicit model ID selected from the configured provider catalogue. No automatic routing."
    ))


class CatalogModelSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=255)
    name = serializers.CharField(max_length=512)
    context_length = serializers.IntegerField(min_value=1, allow_null=True)
    input_price_usd_per_million = serializers.CharField(allow_null=True, help_text=(
        "Advertised USD per million input tokens, or unknown. Not a final charge."
    ))
    output_price_usd_per_million = serializers.CharField(allow_null=True, help_text=(
        "Advertised USD per million output tokens, or unknown. Not a final charge."
    ))
    capabilities = serializers.DictField(child=serializers.BooleanField())


class ModelCatalogResponseSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=PROVIDERS)
    compilation_enabled = serializers.BooleanField()
    credentials_configured = serializers.BooleanField()
    fetched_at = serializers.DateTimeField()
    models = CatalogModelSerializer(many=True)


class CompilationGroundingSerializer(StrictSerializer):
    field = serializers.ChoiceField(choices=["drivers", "horizon", "invalidation_signposts"])
    index = StrictIntegerField(min_value=0, max_value=31, allow_null=True)
    exact_quote = StrictStringField(max_length=1000, help_text=(
        "Exact substring of the supplied thesis. Attribution does not prove semantic accuracy."
    ))


class CompilationRefinementIssueSerializer(StrictSerializer):
    kind = serializers.ChoiceField(choices=[
        "missing_detail", "unsupported_mechanism", "verification_needed", "ambiguity",
        "defensible_disagreement",
    ])
    exact_quote = StrictStringField(max_length=1000, allow_null=True)
    explanation = StrictStringField(max_length=2000)
    question = StrictStringField(max_length=1000)


class CompilationHypothesisSerializer(StrictSerializer):
    explanation = StrictStringField(max_length=2000)
    introduced_assumptions = StrictListField(
        child=StrictStringField(max_length=1000), max_length=32, allow_empty=True,
    )


class CompilationDocumentSerializer(StrictSerializer):
    interpretation = InterpretationInputSerializer()
    grounding = CompilationGroundingSerializer(many=True)
    refinement_issues = CompilationRefinementIssueSerializer(many=True)
    agent_hypotheses = CompilationHypothesisSerializer(many=True)
    counter_case = StrictStringField(max_length=2000, allow_null=True, help_text=(
        "Unverified competing hypothesis, not a sourced factual finding or trading instruction."
    ))


class CompilationUsageSerializer(serializers.Serializer):
    prompt_tokens = serializers.IntegerField(min_value=0, allow_null=True)
    completion_tokens = serializers.IntegerField(min_value=0, allow_null=True)
    total_tokens = serializers.IntegerField(min_value=0, allow_null=True)


class CompilationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=[
        "running", "outcome_unknown", "compiled", "stale", "failed",
    ], help_text=(
        "Explicit attempt disposition. HTTP 200 does not mean compilation succeeded. "
        "An unknown outcome may have incurred provider cost and must not be retried implicitly."
    ))
    provider = serializers.ChoiceField(choices=PROVIDERS)
    model_id = serializers.CharField(max_length=255)
    created_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField(allow_null=True)
    document = CompilationDocumentSerializer(allow_null=True)
    interpretation_version_id = serializers.UUIDField(allow_null=True)
    is_current_draft = serializers.BooleanField(help_text=(
        "Protected response snapshot of whether this interpretation remains the latest draft. "
        "A draft is not user approval or active monitoring."
    ))
    usage = CompilationUsageSerializer()
    reported_cost_usd = serializers.CharField(allow_null=True)
    estimated_cost_usd = serializers.CharField(allow_null=True, help_text=(
        "Estimate from recorded catalogue pricing and reported token usage; unknown is null."
    ))
    reported_model = serializers.CharField(allow_null=True)
    provider_request_id = serializers.CharField(allow_null=True)
    latency_ms = serializers.IntegerField(min_value=0, allow_null=True)
    stop_reason = serializers.CharField(allow_null=True)
    limitations = serializers.ListField(child=serializers.CharField())


class CompilationResponseSerializer(serializers.Serializer):
    compilation = CompilationSerializer()
    thesis = ThesisDetailSerializer()
