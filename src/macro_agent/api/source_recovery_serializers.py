"""Typed source-only recovery policy and safe failure metadata."""

from rest_framework import serializers
from .strict import StrictIntegerField, StrictSerializer, StrictStringField


class SourceRecoveryOutcomeSerializer(StrictSerializer):
    retry_after_seconds = StrictIntegerField(min_value=0, allow_null=True)
    retry_reason = StrictStringField(max_length=64, allow_null=True)
    retry_due_at = serializers.DateTimeField(allow_null=True)


class SourceRecoveryPolicySerializer(StrictSerializer):
    policy_version = serializers.ChoiceField(choices=["research-source-recovery-2026-10-20-v1"], required=False)
    max_attempts_per_question = StrictIntegerField(min_value=3, max_value=3, required=False)
    transport_timeout_seconds = StrictIntegerField(min_value=20, max_value=20, required=False)
    minimum_spacing_seconds = StrictIntegerField(min_value=5, max_value=5, required=False)
    base_backoff_seconds = StrictIntegerField(min_value=30, max_value=30, required=False)
    maximum_backoff_seconds = StrictIntegerField(min_value=300, max_value=300, required=False)
    run_deadline_seconds = StrictIntegerField(min_value=1800, max_value=1800, required=False)

    def validate(self, value):
        if value and set(value) != set(self.fields):
            raise serializers.ValidationError("Recovery policy must be complete or the exact legacy empty object.")
        return value
