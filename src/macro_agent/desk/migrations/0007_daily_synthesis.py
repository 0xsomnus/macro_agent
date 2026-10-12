"""Immutable synthesis admission and result scope, without publication authority."""

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


SQL = r"""
CREATE FUNCTION desk_synthesis_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r macro_desk_dailyreview%ROWTYPE; a macro_desk_dailysynthesisattempt%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME='macro_desk_dailysynthesisattempt' THEN
  SELECT * INTO r FROM macro_desk_dailyreview WHERE id=NEW.review_id;
  IF r.id IS NULL OR r.owner_id IS DISTINCT FROM NEW.owner_id
   OR r.thesis_id IS DISTINCT FROM NEW.thesis_id OR r.digest IS DISTINCT FROM NEW.review_digest
   OR NEW.created_at<r.prepared_at OR NEW.context->>'review_id' IS DISTINCT FROM r.id::text
   OR NEW.context->>'review_digest' IS DISTINCT FROM r.digest
   OR NEW.context->'review' IS DISTINCT FROM r.content
   OR NEW.context->'original_inputs' IS DISTINCT FROM (SELECT resolved_inputs FROM macro_desk_privatecontext WHERE id=r.context_id)
   OR NEW.context->'report_heads' IS DISTINCT FROM (
       SELECT coalesce(jsonb_object_agg(v.report_id::text,to_jsonb(er.head_at_preparation_id::text)), '{}'::jsonb)
       FROM macro_desk_evidencerevision er JOIN macro_monitoring_sourcerevision v ON v.id=er.revision_id
       WHERE er.evidence_id=(SELECT evidence_id FROM macro_desk_privatecontext WHERE id=r.context_id))
   OR jsonb_typeof(NEW.context->'report_heads') IS DISTINCT FROM 'object'
   OR NEW.request_digest !~ '^[0-9a-f]{64}$' OR NEW.context_digest !~ '^[0-9a-f]{64}$'
   OR NOT desk_daily_context_current(r.context_id)
   OR jsonb_typeof(NEW.configuration) IS DISTINCT FROM 'object'
   OR jsonb_typeof(NEW.model_metadata) IS DISTINCT FROM 'object' THEN
   RAISE EXCEPTION 'synthesis admission requires exact scoped retained review' USING ERRCODE='23514';
  END IF;
 ELSE
  SELECT * INTO a FROM macro_desk_dailysynthesisattempt WHERE id=NEW.attempt_id;
  IF a.id IS NULL OR NEW.finished_at<a.created_at
   OR jsonb_typeof(NEW.provider_metadata) IS DISTINCT FROM 'object'
   OR jsonb_typeof(NEW.stale_reasons) IS DISTINCT FROM 'array'
   OR (NEW.document IS NOT NULL AND jsonb_typeof(NEW.document)<>'object')
   OR (NEW.status='stale' AND jsonb_array_length(NEW.stale_reasons)=0)
   OR (NEW.status='synthesised' AND (jsonb_array_length(NEW.stale_reasons)<>0
       OR NEW.finished_at>=a.deadline_at
       OR NOT desk_daily_context_current((SELECT context_id FROM macro_desk_dailyreview WHERE id=a.review_id)))) THEN
   RAISE EXCEPTION 'synthesis result requires valid original scoped disposition' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER desk_synthesis_attempt_scope BEFORE INSERT ON macro_desk_dailysynthesisattempt
 FOR EACH ROW EXECUTE FUNCTION desk_synthesis_scope_guard();
CREATE TRIGGER desk_synthesis_result_scope BEFORE INSERT ON macro_desk_dailysynthesisresult
 FOR EACH ROW EXECUTE FUNCTION desk_synthesis_scope_guard();
CREATE TRIGGER desk_synthesis_attempt_immutable BEFORE UPDATE OR DELETE ON macro_desk_dailysynthesisattempt
 FOR EACH ROW EXECUTE FUNCTION desk_reject_change();
CREATE TRIGGER desk_synthesis_result_immutable BEFORE UPDATE OR DELETE ON macro_desk_dailysynthesisresult
 FOR EACH ROW EXECUTE FUNCTION desk_reject_change();
"""


REVERSE = r"""
DROP TRIGGER IF EXISTS desk_synthesis_attempt_scope ON macro_desk_dailysynthesisattempt;
DROP TRIGGER IF EXISTS desk_synthesis_result_scope ON macro_desk_dailysynthesisresult;
DROP TRIGGER IF EXISTS desk_synthesis_attempt_immutable ON macro_desk_dailysynthesisattempt;
DROP TRIGGER IF EXISTS desk_synthesis_result_immutable ON macro_desk_dailysynthesisresult;
DROP FUNCTION IF EXISTS desk_synthesis_scope_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("macro_desk", "0006_research_evidence"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(name="DailySynthesisAttempt", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("command_id", models.UUIDField()),
            ("request_digest", models.CharField(max_length=64)),
            ("review_digest", models.CharField(max_length=64)),
            ("context", models.JSONField()), ("context_digest", models.CharField(max_length=64)),
            ("provider", models.CharField(max_length=32)), ("model_id", models.CharField(max_length=255)),
            ("model_metadata", models.JSONField()), ("configuration", models.JSONField()),
            ("created_at", models.DateTimeField()), ("deadline_at", models.DateTimeField()),
            ("owner", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ("thesis", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="macro_theses.thesisrecord")),
            ("review", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="macro_desk.dailyreview")),
        ], options={"constraints": [
            models.UniqueConstraint(fields=("owner", "command_id"), name="desk_synthesis_command_once"),
            models.CheckConstraint(condition=models.Q(("deadline_at__gt", models.F("created_at"))), name="desk_synthesis_deadline"),
        ]}),
        migrations.CreateModel(name="DailySynthesisResult", fields=[
            ("attempt", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                primary_key=True, related_name="result", serialize=False, to="macro_desk.dailysynthesisattempt")),
            ("status", models.CharField(max_length=32)), ("document", models.JSONField(null=True)),
            ("provider_metadata", models.JSONField()), ("stop_reason", models.CharField(max_length=64)),
            ("stale_reasons", models.JSONField()), ("finished_at", models.DateTimeField()),
        ], options={"constraints": [
            models.CheckConstraint(condition=models.Q(("status__in", ("synthesised", "stale", "failed", "outcome_unknown"))), name="desk_synthesis_result_status"),
            models.CheckConstraint(condition=~models.Q(("status__in", ("synthesised", "stale"))) | models.Q(("document__isnull", False)), name="desk_synthesis_document_present"),
        ]}),
        migrations.RunSQL(SQL, REVERSE),
    ]
