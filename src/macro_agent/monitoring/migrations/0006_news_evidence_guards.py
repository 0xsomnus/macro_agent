"""Private immutable admissions/results/receipts with scoped authority links."""

from django.db import migrations


SQL = """
ALTER TABLE macro_monitoring_newsanalysisattempt ADD CONSTRAINT monitor_analysis_owner_fk
 FOREIGN KEY (thesis_id, owner_id) REFERENCES macro_theses(id, owner_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_monitoring_newsanalysisattempt ADD CONSTRAINT monitor_analysis_approval_fk
 FOREIGN KEY (thesis_id, approval_id) REFERENCES macro_thesis_approvals(thesis_id, id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_monitoring_newsreviewreceipt ADD CONSTRAINT monitor_receipt_owner_fk
 FOREIGN KEY (thesis_id, owner_id) REFERENCES macro_theses(id, owner_id) DEFERRABLE INITIALLY IMMEDIATE;

CREATE FUNCTION monitor_news_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE admitted timestamptz; deadline timestamptz; source_time timestamptz;
 approved uuid; actual_owner uuid; actual_thesis uuid; command uuid; digest varchar;
BEGIN
 IF TG_TABLE_NAME = 'macro_monitoring_newsanalysisattempt' THEN
  SELECT current_approval_id INTO approved FROM macro_theses WHERE id = NEW.thesis_id;
  SELECT system_received_at INTO source_time FROM macro_monitoring_sourcerevision WHERE id = NEW.source_revision_id;
  IF approved IS DISTINCT FROM NEW.approval_id OR NEW.created_at < source_time
   OR NEW.exposure_digest !~ '^[0-9a-f]{64}$' OR NEW.request_digest !~ '^[0-9a-f]{64}$'
   OR NEW.context_digest !~ '^[0-9a-f]{64}$' OR NEW.prompt_digest !~ '^[0-9a-f]{64}$' THEN
   RAISE EXCEPTION 'invalid news admission authority or evidence' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_monitoring_newsanalysisresult' THEN
  SELECT created_at, deadline_at INTO admitted, deadline FROM macro_monitoring_newsanalysisattempt WHERE id = NEW.attempt_id;
  IF NEW.finished_at < admitted OR (NEW.status IN ('analysed', 'stale') AND NEW.finished_at >= deadline)
   OR (NEW.status = 'stale' AND NEW.stale_reasons = '[]'::jsonb)
   OR (NEW.status = 'analysed' AND NEW.stale_reasons <> '[]'::jsonb) THEN
   RAISE EXCEPTION 'invalid news result time or original disposition' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_monitoring_newsreviewreceipt' THEN
  IF NEW.attempt_id IS NOT NULL THEN
   SELECT owner_id, thesis_id, command_id, request_digest, created_at
    INTO actual_owner, actual_thesis, command, digest, admitted FROM macro_monitoring_newsanalysisattempt WHERE id = NEW.attempt_id;
   IF actual_owner IS DISTINCT FROM NEW.owner_id OR actual_thesis IS DISTINCT FROM NEW.thesis_id
    OR command IS DISTINCT FROM NEW.command_id OR digest IS DISTINCT FROM NEW.request_digest OR NEW.saved_at < admitted THEN
    RAISE EXCEPTION 'news receipt scope mismatch' USING ERRCODE = '23514';
   END IF;
  ELSIF NEW.empty_response #>> '{analysis,status}' IS DISTINCT FROM 'queue_empty' THEN
   RAISE EXCEPTION 'no-call receipt requires empty queue outcome' USING ERRCODE = '23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
"""
TABLES = ("newsanalysisattempt", "newsanalysisresult", "newsreviewreceipt")
SQL += "\n".join(f"CREATE TRIGGER monitor_{name}_immutable BEFORE UPDATE OR DELETE ON macro_monitoring_{name} FOR EACH ROW EXECUTE FUNCTION monitor_evidence_immutable();\nCREATE TRIGGER monitor_{name}_scope BEFORE INSERT ON macro_monitoring_{name} FOR EACH ROW EXECUTE FUNCTION monitor_news_guard();" for name in TABLES)
REVERSE = "\n".join(f"DROP TRIGGER monitor_{name}_immutable ON macro_monitoring_{name};\nDROP TRIGGER monitor_{name}_scope ON macro_monitoring_{name};" for name in TABLES)
REVERSE += """
ALTER TABLE macro_monitoring_newsanalysisattempt DROP CONSTRAINT monitor_analysis_owner_fk;
ALTER TABLE macro_monitoring_newsanalysisattempt DROP CONSTRAINT monitor_analysis_approval_fk;
ALTER TABLE macro_monitoring_newsreviewreceipt DROP CONSTRAINT monitor_receipt_owner_fk;
DROP FUNCTION monitor_news_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("macro_monitoring", "0005_newsreviewreceipt")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
