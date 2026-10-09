"""Explicit model-document and pinned review-card response contracts."""

from rest_framework import serializers

from .strict import StrictSerializer, StrictStringField, StrictIntegerField, StrictListField, StrictUUIDField


class InterpretationInputSerializer(StrictSerializer):
    drivers = StrictListField(child=StrictStringField(max_length=1000), max_length=32, allow_empty=True)
    horizon = StrictStringField(max_length=1000, allow_null=True)
    invalidation_signposts = StrictListField(
        child=StrictStringField(max_length=1000), max_length=32, allow_empty=True,
    )

    def validate_drivers(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Drivers must be unique.")
        return value


class RefinementAnswerSerializer(StrictSerializer):
    question_index = StrictIntegerField(min_value=0, max_value=31)
    exact_answer = StrictStringField(max_length=2000)


class RefinementInputSerializer(RefinementAnswerSerializer):
    input_id = StrictStringField(max_length=100)
    parent_attempt_id = StrictUUIDField()
    question = StrictStringField(max_length=1000)


class CompilationGroundingSerializer(StrictSerializer):
    field = serializers.ChoiceField(choices=["drivers", "horizon", "invalidation_signposts"])
    index = StrictIntegerField(min_value=0, max_value=31, allow_null=True)
    input_id = StrictStringField(max_length=100, required=False, help_text=(
        "Named original thesis or exact trader-answer input. Absent only in historical v1 documents."
    ))
    exact_quote = StrictStringField(max_length=1000)


class CompilationRefinementIssueSerializer(StrictSerializer):
    kind = serializers.ChoiceField(choices=[
        "missing_detail", "unsupported_mechanism", "verification_needed", "ambiguity",
        "defensible_disagreement",
    ])
    input_id = StrictStringField(max_length=100, allow_null=True, required=False)
    exact_quote = StrictStringField(max_length=1000, allow_null=True)
    explanation = StrictStringField(max_length=2000)
    question = StrictStringField(max_length=1000)


class CompilationHypothesisSerializer(StrictSerializer):
    explanation = StrictStringField(max_length=2000)
    introduced_assumptions = StrictListField(
        child=StrictStringField(max_length=1000), max_length=32, allow_empty=True,
    )


class ReviewExtractedItemSerializer(StrictSerializer):
    text = StrictStringField(max_length=1000)
    input_id = StrictStringField(max_length=100)
    exact_quote = StrictStringField(max_length=1000)


class ReviewSectionSerializer(StrictSerializer):
    extracted = ReviewExtractedItemSerializer(many=True)
    proposed = StrictListField(child=StrictStringField(max_length=1000), max_length=32, allow_empty=True)
    gap = StrictStringField(max_length=2000, allow_null=True)


class ReviewSectionsSerializer(StrictSerializer):
    claim = ReviewSectionSerializer()
    affected_assets = ReviewSectionSerializer()
    causal_path = ReviewSectionSerializer()
    assumptions = ReviewSectionSerializer()
    catalysts = ReviewSectionSerializer()
    scenarios = ReviewSectionSerializer()
    monitoring_scope = ReviewSectionSerializer()


class CompilationDocumentSerializer(StrictSerializer):
    interpretation = InterpretationInputSerializer()
    grounding = CompilationGroundingSerializer(many=True)
    refinement_issues = CompilationRefinementIssueSerializer(many=True)
    agent_hypotheses = CompilationHypothesisSerializer(many=True)
    counter_case = StrictStringField(max_length=2000, allow_null=True)
    review_card = ReviewSectionsSerializer(required=False, help_text=(
        "Required for current v2 model output; absent in retained historical v1 documents. "
        "The complete card combines these sections with interpretation, counter-case and questions."
    ))


class ReviewInputSerializer(StrictSerializer):
    input_id = StrictStringField(max_length=100)
    exact_text = StrictStringField(max_length=20000, required=False)
    parent_attempt_id = StrictUUIDField(required=False)
    question_index = StrictIntegerField(min_value=0, max_value=31, required=False)
    question = StrictStringField(max_length=1000, required=False)
    exact_answer = StrictStringField(max_length=2000, required=False)


class UnavailableEvidenceSerializer(StrictSerializer):
    status = serializers.ChoiceField(choices=["unavailable"])
    references = StrictListField(child=StrictStringField(), max_length=0, allow_empty=True)


class PinnedReviewCardSerializer(StrictSerializer):
    schema_version = serializers.ChoiceField(choices=["thesis-review-card-v1"])
    inputs = ReviewInputSerializer(many=True)
    document = CompilationDocumentSerializer()
    evidence = UnavailableEvidenceSerializer()
