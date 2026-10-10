"""Explicit envelopes for internal, read-only retained daily reviews."""

from rest_framework import serializers


class DailyReviewDispositionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["prepared", "stale"])
    stale_reasons = serializers.ListField(child=serializers.CharField())
    observed_at = serializers.DateTimeField(help_text=(
        "Present dependency observation in the read snapshot, not exact commit or delivery time."
    ))
    publication_authority = serializers.ChoiceField(choices=[False])


class DailyReviewSectionCountsSerializer(serializers.Serializer):
    new = serializers.IntegerField(min_value=0)
    background = serializers.IntegerField(min_value=0)
    deferred = serializers.IntegerField(min_value=0)


class DailyReviewCountsSerializer(serializers.Serializer):
    reports = DailyReviewSectionCountsSerializer()
    analyses = DailyReviewSectionCountsSerializer()
    issues = serializers.IntegerField(min_value=0)
    unresolved_analyses = serializers.IntegerField(min_value=0)
    unknown_reported_cost_analyses = serializers.IntegerField(min_value=0)


class DailyReviewSourceReferenceSerializer(serializers.Serializer):
    source_id = serializers.CharField(max_length=128)
    version_id = serializers.UUIDField()
    digest = serializers.CharField(min_length=64, max_length=64)
    provenance = serializers.CharField(max_length=64)
    observed_at = serializers.DateTimeField()
    permitted = serializers.BooleanField()


class DailyReviewSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    command_id = serializers.UUIDField()
    context_id = serializers.UUIDField()
    evidence_set_id = serializers.UUIDField()
    predecessor_id = serializers.UUIDField(allow_null=True)
    start = serializers.DateTimeField()
    cutoff = serializers.DateTimeField()
    prepared_at = serializers.DateTimeField()
    original_outcome = serializers.ChoiceField(choices=["prepared"])
    digest = serializers.CharField(min_length=64, max_length=64, help_text=(
        "Saved content digest. Full retained content integrity is checked by the detail operation."
    ))
    source_manifest = DailyReviewSourceReferenceSerializer(many=True)
    counts = DailyReviewCountsSerializer(help_text=(
        "Counts of the exact retained sections, not coverage, factual validation or materiality."
    ))
    current_disposition = DailyReviewDispositionSerializer()


class DailyReviewListSerializer(serializers.Serializer):
    thesis_id = serializers.UUIDField()
    reviews = DailyReviewSummarySerializer(many=True)
    limit = serializers.IntegerField(min_value=1, max_value=100)
    offset = serializers.IntegerField(min_value=0, max_value=1_000_000)
    total = serializers.IntegerField(min_value=0)
    has_more = serializers.BooleanField()
    observed_at = serializers.DateTimeField()
    publication_authority = serializers.ChoiceField(choices=[False])


class DailyReviewEvidenceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    policy_version = serializers.CharField()
    limits = serializers.JSONField(help_text=(
        "Exact admitted positive record and encoded-byte bounds. Complete assembly fails instead of truncating."
    ))
    source_manifest = DailyReviewSourceReferenceSerializer(many=True)


class RetainedDailyReviewSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    command_id = serializers.UUIDField()
    context_id = serializers.UUIDField()
    evidence_set_id = serializers.UUIDField()
    evidence_set = DailyReviewEvidenceSerializer()
    predecessor_id = serializers.UUIDField(allow_null=True)
    start = serializers.DateTimeField()
    cutoff = serializers.DateTimeField()
    prepared_at = serializers.DateTimeField()
    original_outcome = serializers.ChoiceField(choices=["prepared"])
    digest = serializers.CharField(min_length=64, max_length=64)
    content = serializers.JSONField(help_text=(
        "Exact immutable deterministic review, bounded at assembly by evidence_set.limits. "
        "Includes retained source passages, original analyses, period classifications, gaps and costs. "
        "Prior model documents are hypotheses, not verified facts or a synthesized published brief."
    ))
    original_inputs = serializers.JSONField(help_text=(
        "Exact frozen approved text/interpretation, complete paper exposure, source contracts "
        "and predecessor context under the recorded admitted bounds. Missing macro context stays explicit."
    ))


class DailyReviewDetailSerializer(serializers.Serializer):
    review = RetainedDailyReviewSerializer()
    current_disposition = DailyReviewDispositionSerializer()
    replayed = serializers.BooleanField()
