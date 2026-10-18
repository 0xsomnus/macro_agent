"""Question-led research wire contracts, without approval or monitoring authority."""

from rest_framework import serializers
from .compilation_serializers import CompilationResponseSerializer, CompilationUsageSerializer, PROVIDERS
from .strict import StrictListField, StrictSerializer, StrictStringField, StrictUUIDField


class StartResearchSerializer(StrictSerializer):
    command_id = StrictUUIDField()
    exact_question = StrictStringField(max_length=20000)
    provider_id = serializers.ChoiceField(choices=PROVIDERS)
    model_id = StrictStringField(max_length=255)


class ContinueResearchSerializer(StrictSerializer):
    pass


class ResearchQuestionSerializer(StrictSerializer):
    question_id = StrictStringField(max_length=64)
    question = StrictStringField(max_length=1000)
    why_material = StrictStringField(max_length=2000)
    evidence_to_seek = StrictStringField(max_length=2000)
    counter_evidence_to_seek = StrictStringField(max_length=2000)
    query = StrictStringField(max_length=300)


class ResearchPlanDocumentSerializer(StrictSerializer):
    schema_version = serializers.ChoiceField(choices=["research-plan-v1"])
    questions = ResearchQuestionSerializer(many=True, min_length=1, max_length=3)


class ResearchProviderMetadataSerializer(serializers.Serializer):
    usage = CompilationUsageSerializer(required=False)
    reported_cost_usd = serializers.CharField(allow_null=True, required=False)
    reported_model = serializers.CharField(allow_null=True, required=False)
    provider_request_id = serializers.CharField(allow_null=True, required=False)
    latency_ms = serializers.IntegerField(min_value=0, required=False)
    finish_reason = serializers.CharField(allow_null=True, required=False)


class ResearchPlanNodeSerializer(serializers.Serializer):
    attempt_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=["planned", "stale", "failed", "outcome_unknown", "running"])
    document = ResearchPlanDocumentSerializer(allow_null=True)
    stop_reason = serializers.CharField(allow_null=True)
    provider_metadata = ResearchProviderMetadataSerializer()
    created_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField(allow_null=True)


class ResearchArticleMetadataSerializer(StrictSerializer):
    url = StrictStringField(max_length=2048)
    title = StrictStringField(max_length=2048)
    seendate = StrictStringField(max_length=253)
    domain = StrictStringField(max_length=253, allow_blank=True)
    language = StrictStringField(max_length=253, allow_blank=True)
    sourcecountry = StrictStringField(max_length=253, allow_blank=True)
    url_mobile = StrictStringField(max_length=2048, allow_blank=True, required=False)
    socialimage = StrictStringField(max_length=2048, allow_blank=True, required=False)


class ResearchCandidateSerializer(serializers.Serializer):
    rank = serializers.IntegerField(min_value=1, max_value=5)
    native_id = serializers.CharField()
    selected = serializers.BooleanField()
    exclusion_reason = serializers.CharField(allow_null=True)
    gdelt_seen_at = serializers.DateTimeField()
    metadata = ResearchArticleMetadataSerializer()


class ResearchSelectionSerializer(serializers.Serializer):
    schema_version = serializers.ChoiceField(choices=["gdelt-research-selection-v1"])
    query = serializers.CharField()
    request_url = serializers.CharField()
    received_at = serializers.DateTimeField()
    transport_digest = serializers.CharField(min_length=64, max_length=64)
    requested_candidate_limit = serializers.IntegerField(min_value=1, max_value=5)
    selection_limit = serializers.IntegerField(min_value=1, max_value=4)
    returned_candidate_count = serializers.IntegerField(min_value=0, max_value=5)
    selected_count = serializers.IntegerField(min_value=0, max_value=4)
    candidate_cap_reached = serializers.BooleanField()
    coverage_complete = serializers.BooleanField()
    candidates = ResearchCandidateSerializer(many=True, max_length=5)
    limitations = serializers.ListField(child=serializers.CharField())


class ResearchDiscoveryNodeSerializer(serializers.Serializer):
    question_index = serializers.IntegerField(min_value=0, max_value=2)
    question_id = serializers.CharField()
    source_id = serializers.CharField()
    status = serializers.ChoiceField(choices=["captured", "failed", "outcome_unknown", "running"])
    capture_id = serializers.UUIDField(allow_null=True)
    revision_ids = serializers.ListField(child=serializers.UUIDField(), max_length=4)
    metadata = ResearchSelectionSerializer(allow_null=True)
    stop_reason = serializers.CharField(allow_null=True)
    admitted_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField(allow_null=True)


class ResearchBoundsSerializer(serializers.Serializer):
    max_model_calls = serializers.IntegerField()
    max_questions = serializers.IntegerField()
    max_results_per_question = serializers.IntegerField()
    max_selected_reports = serializers.IntegerField()


class ResearchAuthoritySerializer(serializers.Serializer):
    monitoring_started = serializers.ChoiceField(choices=[False])
    thesis_approved = serializers.ChoiceField(choices=[False])
    positions_created = serializers.ChoiceField(choices=[False])


class ResearchCostsSerializer(serializers.Serializer):
    planning_reported_cost_usd = serializers.CharField(allow_null=True)
    compilation_reported_cost_usd = serializers.CharField(allow_null=True)
    total_known_cost_usd = serializers.CharField(allow_null=True)


class ResearchRunSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    command_id = serializers.UUIDField()
    exact_question = serializers.CharField(trim_whitespace=False)
    thesis_id = serializers.UUIDField()
    initial_thesis_revision = serializers.IntegerField(min_value=1)
    provider = serializers.ChoiceField(choices=PROVIDERS)
    model_id = serializers.CharField()
    created_at = serializers.DateTimeField()
    request_digest = serializers.CharField(min_length=64, max_length=64)
    bounds = ResearchBoundsSerializer()
    status = serializers.ChoiceField(choices=["planning", "plan_failed", "plan_uncertain", "discovering",
        "discovery_failed", "discovery_uncertain", "no_evidence", "ready_to_compile", "compiling",
        "compiled", "compile_failed", "compile_uncertain", "stale"], help_text=(
        "Inspect node outcomes and gaps; HTTP 200 does not establish completed or useful research."))
    plan = ResearchPlanNodeSerializer(allow_null=True)
    discoveries = ResearchDiscoveryNodeSerializer(many=True, max_length=3)
    evidence_context_id = serializers.UUIDField(allow_null=True)
    compilation = CompilationResponseSerializer(allow_null=True)
    gaps = serializers.ListField(child=serializers.CharField())
    authority = ResearchAuthoritySerializer()
    costs = ResearchCostsSerializer()


class ResearchRunResponseSerializer(serializers.Serializer):
    research = ResearchRunSerializer()
    replayed = serializers.BooleanField()
