"""Typed explanatory assessments, separate from publication or trader authority."""

from rest_framework import serializers
from .strict import StrictIntegerField, StrictListField, StrictSerializer, StrictStringField, StrictUUIDField


class DriverSupportSerializer(StrictSerializer):
    status = serializers.ChoiceField(choices=["supports", "challenges", "mixed", "unresolved"])
    claim_ids = StrictListField(child=StrictStringField(max_length=2000), max_length=16)
    prior_analysis_ids = StrictListField(child=StrictUUIDField(), max_length=16)
    reasoning = StrictStringField(max_length=2000)
    uncertainty = StrictStringField(max_length=2000)


class ApprovedDriverReviewSerializer(StrictSerializer):
    driver_index = StrictIntegerField(min_value=0, max_value=31)
    exact_driver = StrictStringField(max_length=1000)
    premise = DriverSupportSerializer()
    mechanism = DriverSupportSerializer()
    discriminating_questions = StrictListField(child=StrictStringField(max_length=2000), max_length=16)


class OtherDriverSerializer(StrictSerializer):
    hypothesis_id = StrictStringField(max_length=2000)
    relationship = serializers.ChoiceField(choices=["competing", "amplifying", "offsetting", "additional"])
    driver_indices = StrictListField(child=StrictIntegerField(min_value=0, max_value=31), max_length=32)
    claim_ids = StrictListField(child=StrictStringField(max_length=2000), min_length=1, max_length=16)
    counter_claim_ids = StrictListField(child=StrictStringField(max_length=2000), max_length=16)
    prior_analysis_ids = StrictListField(child=StrictUUIDField(), max_length=16)
    explanation = StrictStringField(max_length=2000)
    transmission = StrictStringField(max_length=2000)
    assumptions = StrictListField(child=StrictStringField(max_length=2000), max_length=16)
    uncertainty = StrictStringField(max_length=2000)
    discriminating_questions = StrictListField(child=StrictStringField(max_length=2000), max_length=16)


class ThesisProgressionSerializer(DriverSupportSerializer):
    status = serializers.ChoiceField(choices=["progressing", "not_progressing", "mixed", "unresolved"])


class UnavailablePriceSerializer(StrictSerializer):
    status = serializers.ChoiceField(choices=["unavailable"])
    gaps = StrictListField(child=StrictStringField(max_length=2000), min_length=1, max_length=16)


class UnassessedEntrySerializer(UnavailablePriceSerializer):
    status = serializers.ChoiceField(choices=["not_assessed"])


class DriverAttentionSerializer(DriverSupportSerializer):
    status = serializers.ChoiceField(choices=["review_recommended", "not_identified"])
    driver_indices = StrictListField(child=StrictIntegerField(min_value=0, max_value=31), max_length=32)


class DriverAssessmentSerializer(StrictSerializer):
    approved_drivers = ApprovedDriverReviewSerializer(many=True, max_length=32)
    other_drivers = OtherDriverSerializer(many=True, max_length=16)
    progression = ThesisProgressionSerializer()
    price_observation = UnavailablePriceSerializer()
    entry_assessment = UnassessedEntrySerializer()
    attention = DriverAttentionSerializer(help_text=(
        "Analytical recommendation only. It cannot publish, notify, suppress monitoring or amend approved belief."
    ))
