"""Strict commands and retained background research provenance."""

import re

from rest_framework import serializers

from .compilation_serializers import PROVIDERS
from .strict import StrictSerializer, StrictStringField, StrictUUIDField


class EnrollResearchBackgroundSerializer(StrictSerializer):
    command_id = StrictUUIDField()
    expected_request_digest = StrictStringField(min_length=64, max_length=64)

    def validate_expected_request_digest(self, value):
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise serializers.ValidationError("A lowercase SHA-256 digest is required.")
        return value


class RevokeResearchBackgroundSerializer(StrictSerializer):
    command_id = StrictUUIDField()


class ResearchBackgroundModelConfigurationSerializer(serializers.Serializer):
    max_output_tokens = serializers.IntegerField(min_value=128, max_value=4000)
    timeout_seconds = serializers.IntegerField(min_value=1, max_value=60)
    owner_attempts_per_day = serializers.IntegerField(min_value=1, max_value=100)
    aggregate_attempts_per_day = serializers.IntegerField(min_value=1, max_value=1000)
    provider = serializers.ChoiceField(choices=PROVIDERS)
    prompt_version = serializers.CharField()
    schema_version = serializers.CharField()
    calls_per_attempt = serializers.IntegerField(min_value=1, max_value=1)
    automatic_retries = serializers.IntegerField(min_value=0, max_value=0)
    cost_category = serializers.CharField()
    context = serializers.CharField()


class ResearchBackgroundPolicySerializer(serializers.Serializer):
    """Fields are pinned at consent, not supplied by a client command."""

    policy_version = serializers.ChoiceField(choices=["research-background-resume-2026-10-21-v1"])
    lease_seconds = serializers.IntegerField(min_value=180, max_value=180)
    max_leases = serializers.IntegerField(min_value=12, max_value=12)
    planning_allowed = serializers.ChoiceField(choices=[(False, False)])
    model_retries_allowed = serializers.ChoiceField(choices=[(False, False)])


class ResearchBackgroundOutcomeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["pending", "blocked", "completed", "expired", "revoked"])
    reason = serializers.CharField(max_length=96)
    finished_at = serializers.DateTimeField()


class ResearchBackgroundAdmissionSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["source", "compilation"])
    admission_id = serializers.UUIDField()
    admitted_at = serializers.DateTimeField()


class ResearchBackgroundLeaseSerializer(serializers.Serializer):
    token = serializers.UUIDField()
    sequence = serializers.IntegerField(min_value=1)
    admitted_at = serializers.DateTimeField()
    deadline_at = serializers.DateTimeField()
    outcome = ResearchBackgroundOutcomeSerializer(allow_null=True)
    admissions = ResearchBackgroundAdmissionSerializer(many=True)


class ResearchBackgroundSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    run_id = serializers.UUIDField()
    owner_id = serializers.CharField()
    enrollment_command_id = serializers.UUIDField()
    request_digest = serializers.CharField(min_length=64, max_length=64)
    policy = ResearchBackgroundPolicySerializer()
    provider = serializers.ChoiceField(choices=PROVIDERS)
    model_id = serializers.CharField(max_length=255)
    model_configuration = ResearchBackgroundModelConfigurationSerializer()
    status = serializers.ChoiceField(choices=["pending", "running", "blocked", "completed", "revoked"])
    next_due_at = serializers.DateTimeField(allow_null=True)
    active_token = serializers.UUIDField(allow_null=True)
    lease_deadline_at = serializers.DateTimeField(allow_null=True)
    last_stop_reason = serializers.CharField(max_length=96)
    created_at = serializers.DateTimeField()
    changed_at = serializers.DateTimeField()
    revoked_at = serializers.DateTimeField(allow_null=True)
    leases = ResearchBackgroundLeaseSerializer(many=True, max_length=12)


class ResearchBackgroundResponseSerializer(serializers.Serializer):
    job = ResearchBackgroundSerializer()
    replayed = serializers.BooleanField()
