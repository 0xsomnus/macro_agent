"""Opted-in driver review preserves explicit legacy cumulative admission pairs."""

from django.db import migrations


LEGACY = """
CREATE OR REPLACE FUNCTION monitor_cumulative_admission_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE pinned macro_desk_privatecontext%ROWTYPE;
BEGIN
 IF NEW.admission_context_id IS NULL THEN
  IF NEW.context ? 'cumulative' OR NEW.configuration ->> 'context' = 'complete_retained_context' THEN
   RAISE EXCEPTION 'cumulative admission requires a retained private context' USING ERRCODE = '23514';
  END IF;
 ELSE
  SELECT * INTO pinned FROM macro_desk_privatecontext WHERE id = NEW.admission_context_id;
  IF pinned.id IS NULL OR pinned.owner_id IS DISTINCT FROM NEW.owner_id
   OR pinned.thesis_id IS DISTINCT FROM NEW.thesis_id OR pinned.approval_id IS DISTINCT FROM NEW.approval_id
   OR pinned.exposure_digest IS DISTINCT FROM NEW.exposure_digest OR pinned.prepared_at IS DISTINCT FROM NEW.created_at
   OR NEW.configuration ->> 'context' IS DISTINCT FROM 'complete_retained_context'
   OR NEW.configuration ->> 'schema_version' IS DISTINCT FROM 'retained-news-analysis-v2'
   OR NEW.configuration ->> 'prompt_version' IS DISTINCT FROM 'retained-news-analysis-prompt-v3'
   OR NEW.context -> 'cumulative' IS DISTINCT FROM pinned.resolved_inputs -> 'cumulative'
   OR NEW.context #>> '{cumulative,context_id}' IS DISTINCT FROM pinned.id::text
   OR COALESCE(NEW.context #>> '{cumulative,digest}', '') !~ '^[0-9a-f]{64}$'
   OR NOT EXISTS (SELECT 1 FROM macro_desk_evidencerevision member
     WHERE member.evidence_id = pinned.evidence_id AND member.revision_id = NEW.source_revision_id)
   OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.context #> '{cumulative,reports}') item
     WHERE item ->> 'revision_id' = NEW.source_revision_id::text) THEN
   RAISE EXCEPTION 'cumulative admission context authority or evidence mismatch' USING ERRCODE = '23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
"""

# New profile metadata must agree even for a single-report admission. Absence
# remains the legacy profile; false, null and a lone version change are invalid.
PROFILE_GUARD = """
 IF NEW.context ? 'driver_review' OR NEW.configuration ? 'driver_review'
  OR NEW.configuration ->> 'schema_version' = 'driver-reviewed-news-analysis-v1'
  OR NEW.configuration ->> 'prompt_version' = 'driver-reviewed-news-prompt-v1' THEN
  IF NEW.context -> 'driver_review' IS DISTINCT FROM 'true'::jsonb
   OR NEW.configuration -> 'driver_review' IS DISTINCT FROM 'true'::jsonb
   OR NEW.configuration ->> 'schema_version' IS DISTINCT FROM 'driver-reviewed-news-analysis-v1'
   OR NEW.configuration ->> 'prompt_version' IS DISTINCT FROM 'driver-reviewed-news-prompt-v1' THEN
   RAISE EXCEPTION 'driver review admission profile mismatch' USING ERRCODE = '23514';
  END IF;
 END IF;
"""

LEGACY_PAIR = """   OR NEW.configuration ->> 'schema_version' IS DISTINCT FROM 'retained-news-analysis-v2'
   OR NEW.configuration ->> 'prompt_version' IS DISTINCT FROM 'retained-news-analysis-prompt-v3'"""
VERSIONED_PAIR = """   OR NOT (
     (NEW.configuration ->> 'schema_version' IS NOT DISTINCT FROM 'retained-news-analysis-v2'
      AND NEW.configuration ->> 'prompt_version' IS NOT DISTINCT FROM 'retained-news-analysis-prompt-v3'
      AND NOT (NEW.context ? 'driver_review') AND NOT (NEW.configuration ? 'driver_review'))
     OR (NEW.configuration ->> 'schema_version' IS NOT DISTINCT FROM 'driver-reviewed-news-analysis-v1'
      AND NEW.configuration ->> 'prompt_version' IS NOT DISTINCT FROM 'driver-reviewed-news-prompt-v1'
      AND NEW.context -> 'driver_review' IS NOT DISTINCT FROM 'true'::jsonb
      AND NEW.configuration -> 'driver_review' IS NOT DISTINCT FROM 'true'::jsonb))"""
SQL = LEGACY.replace("BEGIN\n", "BEGIN\n" + PROFILE_GUARD, 1).replace(LEGACY_PAIR, VERSIONED_PAIR)


class Migration(migrations.Migration):
    dependencies = [("macro_monitoring", "0007_cumulative_admission_context")]
    operations = [migrations.RunSQL(SQL, LEGACY)]
