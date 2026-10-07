"""Keep pending work durable and align direct writes with recovery contracts."""

from django.db import migrations


SQL = """
CREATE FUNCTION monitor_recovery_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE deadline timestamptz;
BEGIN
 IF TG_TABLE_NAME = 'macro_monitoring_sourcestate' THEN
  IF OLD.active_capture IS NOT NULL AND NEW.active_capture IS DISTINCT FROM OLD.active_capture
   AND NOT EXISTS (SELECT 1 FROM macro_monitoring_captureoutcome WHERE attempt_id = OLD.active_capture) THEN
   RAISE EXCEPTION 'replaced capture requires disposition' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_monitoring_screeningwork' THEN
  IF NEW.state <> 'pending' OR NEW.attempt_count <> 0 OR NEW.active_token IS NOT NULL OR NEW.lease_until IS NOT NULL THEN
   RAISE EXCEPTION 'new work must be pending' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_monitoring_screeningresult' THEN
  SELECT deadline_at INTO deadline FROM macro_monitoring_screeningattempt WHERE token = NEW.attempt_id;
  IF NEW.finished_at >= deadline THEN
   RAISE EXCEPTION 'expired attempt cannot complete' USING ERRCODE = '23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER monitor_source_recovery BEFORE UPDATE ON macro_monitoring_sourcestate
 FOR EACH ROW EXECUTE FUNCTION monitor_recovery_guard();
CREATE TRIGGER monitor_work_initial BEFORE INSERT ON macro_monitoring_screeningwork
 FOR EACH ROW EXECUTE FUNCTION monitor_recovery_guard();
CREATE TRIGGER monitor_result_deadline BEFORE INSERT ON macro_monitoring_screeningresult
 FOR EACH ROW EXECUTE FUNCTION monitor_recovery_guard();
"""
SQL += "\n".join(f"CREATE TRIGGER monitor_{name}_no_delete BEFORE DELETE ON macro_monitoring_{name} FOR EACH ROW EXECUTE FUNCTION monitor_evidence_immutable();" for name in ("sourcestate", "sourcereport", "screeningwork"))

REVERSE = "\n".join(f"DROP TRIGGER monitor_{name}_no_delete ON macro_monitoring_{name};" for name in ("sourcestate", "sourcereport", "screeningwork"))
REVERSE += """
DROP TRIGGER monitor_source_recovery ON macro_monitoring_sourcestate;
DROP TRIGGER monitor_work_initial ON macro_monitoring_screeningwork;
DROP TRIGGER monitor_result_deadline ON macro_monitoring_screeningresult;
DROP FUNCTION monitor_recovery_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("macro_monitoring", "0002_evidence_guards")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
