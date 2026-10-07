"""Immutable evidence, scoped links, and monotonic observed/work state."""

from django.db import migrations


IMMUTABLE = ("captureattempt", "captureoutcome", "sourcerevision", "capturemembership",
             "durableobservation", "screeningattempt", "screeningresult")

SQL = """
CREATE FUNCTION monitor_evidence_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'monitor evidence is immutable' USING ERRCODE = '23514'; END $$;

ALTER TABLE macro_monitoring_sourcereport ADD CONSTRAINT monitor_head_scope_fk
 FOREIGN KEY (id, current_revision_id) REFERENCES macro_monitoring_sourcerevision(report_id, id)
 DEFERRABLE INITIALLY IMMEDIATE;

CREATE FUNCTION monitor_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected_source varchar; actual_source varchar; admitted timestamptz; received timestamptz;
BEGIN
 IF TG_TABLE_NAME = 'macro_monitoring_sourcerevision' THEN
  SELECT source_id INTO expected_source FROM macro_monitoring_sourcereport WHERE id = NEW.report_id;
  SELECT source_id, admitted_at INTO actual_source, admitted FROM macro_monitoring_captureattempt WHERE id = NEW.capture_id;
  IF expected_source IS DISTINCT FROM actual_source OR NEW.system_received_at < admitted THEN
   RAISE EXCEPTION 'revision capture scope/time mismatch' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_monitoring_capturemembership' THEN
  SELECT source_id INTO expected_source FROM macro_monitoring_captureattempt WHERE id = NEW.capture_id;
  SELECT r.source_id INTO actual_source FROM macro_monitoring_sourcerevision v
   JOIN macro_monitoring_sourcereport r ON r.id = v.report_id WHERE v.id = NEW.revision_id;
  IF expected_source IS DISTINCT FROM actual_source THEN
   RAISE EXCEPTION 'membership source mismatch' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_monitoring_durableobservation' THEN
  SELECT system_received_at INTO received FROM macro_monitoring_sourcerevision WHERE id = NEW.revision_id;
  IF NEW.observed_by_at < received OR NEW.method <> 'postcommit_read' THEN
   RAISE EXCEPTION 'invalid durable observation' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_monitoring_captureoutcome' THEN
  SELECT admitted_at INTO admitted FROM macro_monitoring_captureattempt WHERE id = NEW.attempt_id;
  IF NEW.finished_at < admitted OR NEW.item_count > 100 OR NEW.new_revision_count > NEW.item_count THEN
   RAISE EXCEPTION 'invalid capture disposition' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_monitoring_screeningresult' THEN
  SELECT admitted_at INTO admitted FROM macro_monitoring_screeningattempt WHERE token = NEW.attempt_id;
  IF NEW.finished_at < admitted THEN
   RAISE EXCEPTION 'invalid screening time' USING ERRCODE = '23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION monitor_state_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE active_source varchar; active_sequence bigint; head_number integer; lease timestamptz;
BEGIN
 IF TG_TABLE_NAME = 'macro_monitoring_sourcestate' THEN
  IF NEW.id <> OLD.id OR NEW.contract IS DISTINCT FROM OLD.contract
   OR NEW.contract_digest <> OLD.contract_digest OR NEW.capture_sequence < OLD.capture_sequence
   OR NEW.capture_sequence > OLD.capture_sequence + 1 THEN
   RAISE EXCEPTION 'invalid source state transition' USING ERRCODE = '23514';
  END IF;
  IF NEW.active_capture IS NOT NULL THEN
   SELECT source_id, sequence INTO active_source, active_sequence FROM macro_monitoring_captureattempt WHERE id = NEW.active_capture;
   IF active_source IS DISTINCT FROM NEW.id OR active_sequence IS DISTINCT FROM NEW.capture_sequence THEN
    RAISE EXCEPTION 'active capture scope mismatch' USING ERRCODE = '23514';
   END IF;
  ELSIF OLD.active_capture IS NOT NULL AND NOT EXISTS
   (SELECT 1 FROM macro_monitoring_captureoutcome WHERE attempt_id = OLD.active_capture) THEN
   RAISE EXCEPTION 'capture cannot disappear without disposition' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_monitoring_sourcereport' THEN
  SELECT observation_revision INTO head_number FROM macro_monitoring_sourcerevision WHERE id = NEW.current_revision_id;
  IF NEW.source_id <> OLD.source_id OR NEW.native_id <> OLD.native_id
   OR NEW.revision_count <> OLD.revision_count + 1 OR head_number IS DISTINCT FROM NEW.revision_count THEN
   RAISE EXCEPTION 'invalid observed head transition' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_monitoring_screeningwork' THEN
  IF NEW.revision_id <> OLD.revision_id OR NEW.attempt_count < OLD.attempt_count
   OR NEW.attempt_count > OLD.attempt_count + 1 OR OLD.state = 'superseded'
   OR (OLD.state = 'completed' AND NEW.state <> 'superseded') THEN
   RAISE EXCEPTION 'invalid work transition' USING ERRCODE = '23514';
  END IF;
  IF NEW.state = 'running' THEN
   SELECT sequence, deadline_at INTO active_sequence, lease FROM macro_monitoring_screeningattempt
    WHERE token = NEW.active_token AND work_id = NEW.revision_id;
   IF active_sequence IS DISTINCT FROM NEW.attempt_count OR lease IS DISTINCT FROM NEW.lease_until
    OR NEW.attempt_count <> OLD.attempt_count + 1 THEN
    RAISE EXCEPTION 'work lease scope mismatch' USING ERRCODE = '23514';
   END IF;
  ELSIF NEW.state = 'completed' THEN
   IF OLD.state <> 'running' OR NOT EXISTS
    (SELECT 1 FROM macro_monitoring_screeningresult WHERE attempt_id = OLD.active_token) THEN
    RAISE EXCEPTION 'work completion requires original result' USING ERRCODE = '23514';
   END IF;
  ELSIF NEW.state <> 'superseded' THEN
   RAISE EXCEPTION 'work cannot return to pending' USING ERRCODE = '23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
"""
SQL += "\n".join(f"CREATE TRIGGER monitor_{name}_immutable BEFORE UPDATE OR DELETE ON macro_monitoring_{name} FOR EACH ROW EXECUTE FUNCTION monitor_evidence_immutable();" for name in IMMUTABLE)
SQL += "\n" + "\n".join(f"CREATE TRIGGER monitor_{name}_scope BEFORE INSERT ON macro_monitoring_{name} FOR EACH ROW EXECUTE FUNCTION monitor_scope_guard();" for name in ("sourcerevision", "capturemembership", "durableobservation", "captureoutcome", "screeningresult"))
SQL += "\n" + "\n".join(f"CREATE TRIGGER monitor_{name}_transition BEFORE UPDATE ON macro_monitoring_{name} FOR EACH ROW EXECUTE FUNCTION monitor_state_guard();" for name in ("sourcestate", "sourcereport", "screeningwork"))

REVERSE = "\n".join(f"DROP TRIGGER monitor_{name}_immutable ON macro_monitoring_{name};" for name in IMMUTABLE)
REVERSE += "\n" + "\n".join(f"DROP TRIGGER monitor_{name}_scope ON macro_monitoring_{name};" for name in ("sourcerevision", "capturemembership", "durableobservation", "captureoutcome", "screeningresult"))
REVERSE += "\n" + "\n".join(f"DROP TRIGGER monitor_{name}_transition ON macro_monitoring_{name};" for name in ("sourcestate", "sourcereport", "screeningwork"))
REVERSE += "\nALTER TABLE macro_monitoring_sourcereport DROP CONSTRAINT monitor_head_scope_fk;\nDROP FUNCTION monitor_evidence_immutable();\nDROP FUNCTION monitor_scope_guard();\nDROP FUNCTION monitor_state_guard();"


class Migration(migrations.Migration):
    dependencies = [("macro_monitoring", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
