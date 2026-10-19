"""Explicit selected-source packet and attributable model claim contracts."""

from rest_framework import serializers
from .strict import (StrictSerializer, StrictStringField, StrictListField, StrictUUIDField,
                     StrictIntegerField, StrictBooleanField)


class PlannedResearchQuestionSerializer(StrictSerializer):
    question_id = StrictStringField(max_length=64)
    question = StrictStringField(max_length=1000)
    why_material = StrictStringField(max_length=2000)
    evidence_to_seek = StrictStringField(max_length=2000)
    counter_evidence_to_seek = StrictStringField(max_length=2000)
    query = StrictStringField(max_length=300)


class ResearchExclusionCountsSerializer(StrictSerializer):
    duplicate_url_identity = StrictIntegerField(min_value=1, max_value=5, required=False)
    unsafe_or_non_https_attribution_url = StrictIntegerField(min_value=1, max_value=5, required=False)
    explicit_selection_limit = StrictIntegerField(min_value=1, max_value=5, required=False)


class QuestionResearchOutcomeSerializer(StrictSerializer):
    question_index = StrictIntegerField(min_value=0, max_value=2)
    planned_question = PlannedResearchQuestionSerializer()
    source_id = StrictStringField(max_length=128)
    discovery_attempt_id = StrictUUIDField()
    contract_version_id = StrictUUIDField()
    contract_digest = StrictStringField(min_length=64, max_length=64)
    receipt_id = StrictUUIDField()
    receipt_digest = StrictStringField(min_length=64, max_length=64)
    result_id = StrictUUIDField()
    result_digest = StrictStringField(min_length=64, max_length=64)
    capture_id = StrictUUIDField()
    status = serializers.ChoiceField(choices=["captured"])
    returned_candidate_count = StrictIntegerField(min_value=0, max_value=5)
    selected_count = StrictIntegerField(min_value=0, max_value=4)
    excluded_count = StrictIntegerField(min_value=0, max_value=5)
    exclusion_counts = ResearchExclusionCountsSerializer()
    candidate_cap_reached = StrictBooleanField()
    revision_ids = StrictListField(child=StrictUUIDField(), max_length=4)


class QuestionResearchContextSerializer(StrictSerializer):
    schema_version = serializers.ChoiceField(choices=["question-research-context-v1"])
    run_id = StrictUUIDField()
    run_request_digest = StrictStringField(min_length=64, max_length=64)
    exact_question_digest = StrictStringField(min_length=64, max_length=64)
    plan_attempt_id = StrictUUIDField()
    plan_prompt_digest = StrictStringField(min_length=64, max_length=64)
    plan_result_id = StrictUUIDField()
    plan_result_digest = StrictStringField(min_length=64, max_length=64)
    evidence_depth = serializers.ChoiceField(choices=["headline_metadata_only"])
    coverage_complete = serializers.ChoiceField(choices=[(False, False)])
    questions = QuestionResearchOutcomeSerializer(many=True, min_length=1, max_length=3)


class SourceEvidenceReportSerializer(StrictSerializer):
    revision_id = StrictUUIDField()
    source_id = StrictStringField(max_length=128)
    title = StrictStringField(max_length=4096)
    content = StrictStringField(max_length=16384, allow_blank=True)
    source_url = StrictStringField(max_length=4096)
    source_claimed_published_at = serializers.DateTimeField(allow_null=True)
    system_received_at = serializers.DateTimeField()
    availability_witness_at = serializers.DateTimeField()
    contract_version_id = StrictUUIDField()
    contract_digest = StrictStringField(min_length=64, max_length=64)
    head_at_admission_id = StrictUUIDField()


class SourceEvidenceEnvelopeSerializer(StrictSerializer):
    schema_version = serializers.ChoiceField(choices=["retained-source-evidence-v1", "retained-source-evidence-v2"])
    cutoff = serializers.DateTimeField()
    reports = SourceEvidenceReportSerializer(many=True, min_length=1, max_length=16)
    gaps = StrictListField(child=StrictStringField(max_length=2000), max_length=32)
    question_research = QuestionResearchContextSerializer(required=False)

    def validate(self, value):
        contextual = value["schema_version"] == "retained-source-evidence-v2"
        if contextual != ("question_research" in value):
            raise serializers.ValidationError("Source evidence must match its exact retained variant.")
        return value


class EvidenceDispositionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["current", "stale"])
    stale_reasons = serializers.ListField(child=serializers.CharField())
    observed_at = serializers.DateTimeField()


class PrepareEvidenceSerializer(StrictSerializer):
    command_id = StrictUUIDField()
    revision_ids = StrictListField(child=StrictUUIDField(), min_length=1, max_length=16)

    def validate_revision_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Selected revisions must be unique.")
        return value


class EvidenceContextSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    command_id = serializers.UUIDField()
    thesis_id = serializers.UUIDField()
    digest = serializers.CharField(min_length=64, max_length=64)
    content = SourceEvidenceEnvelopeSerializer()
    created_at = serializers.DateTimeField()


class EvidenceResponseSerializer(serializers.Serializer):
    evidence = EvidenceContextSerializer()
    current_disposition = EvidenceDispositionSerializer()
    replayed = serializers.BooleanField()


class AttributedSourceClaimSerializer(StrictSerializer):
    claim_id = StrictStringField(max_length=128)
    revision_id = StrictUUIDField()
    field = serializers.ChoiceField(choices=["title", "content"])
    exact_quote = StrictStringField(max_length=2000)


class FactualConflictSerializer(StrictSerializer):
    status = serializers.ChoiceField(choices=["model_identified"])
    input_id = StrictStringField(max_length=100)
    exact_quote = StrictStringField(max_length=1000)
    claim_ids = StrictListField(child=StrictStringField(max_length=128), max_length=32)
    explanation = StrictStringField(max_length=2000)
    question = StrictStringField(max_length=1000)


class EvidenceAssessmentSerializer(StrictSerializer):
    summary = StrictStringField(max_length=2000)
    supporting_claim_ids = StrictListField(child=StrictStringField(max_length=128), max_length=32)
    counter_claim_ids = StrictListField(child=StrictStringField(max_length=128), max_length=32)
    gaps = StrictListField(child=StrictStringField(max_length=1000), max_length=32)
