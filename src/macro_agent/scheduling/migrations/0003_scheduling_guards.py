"""Scoped immutable admissions, monotonic cursors and terminal lease history."""

from django.db import migrations


IMMUTABLE = ("watchversion", "slotlease", "slotoutcome", "analysisdispatch")
SQL = """
CREATE FUNCTION schedule_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'scheduling evidence is immutable' USING ERRCODE = '23514'; END $$;

CREATE FUNCTION schedule_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE w macro_scheduling_watchrecord; s macro_scheduling_scheduledslot;
 v macro_scheduling_watchversion; l macro_scheduling_slotlease; expected_owner uuid;
BEGIN
 IF TG_TABLE_NAME = 'macro_scheduling_watchrecord' THEN
  SELECT owner_id INTO expected_owner FROM macro_theses WHERE id = NEW.thesis_id;
  IF NEW.owner_id IS DISTINCT FROM expected_owner OR NEW.revision <> 0 OR NEW.current_version_id IS NOT NULL THEN
   RAISE EXCEPTION 'watch must begin in its owner thesis scope' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_scheduling_watchversion' THEN
  SELECT * INTO w FROM macro_scheduling_watchrecord WHERE id = NEW.watch_id;
  IF NEW.owner_id IS DISTINCT FROM w.owner_id OR NEW.sequence <> w.revision + 1
   OR NEW.created_at < w.changed_at OR jsonb_typeof(NEW.configuration) <> 'object'
   OR NEW.configuration->>'schema_version' IS DISTINCT FROM 'internal-desk-watch-v1' THEN
   RAISE EXCEPTION 'watch version scope/time/configuration mismatch' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_scheduling_scheduledslot' THEN
  SELECT * INTO w FROM macro_scheduling_watchrecord WHERE id = NEW.watch_id;
  SELECT * INTO v FROM macro_scheduling_watchversion WHERE id = NEW.watch_version_id;
  IF NEW.owner_id IS DISTINCT FROM w.owner_id OR NEW.thesis_id IS DISTINCT FROM w.thesis_id
   OR v.watch_id IS DISTINCT FROM w.id OR NEW.watch_version_id IS DISTINCT FROM w.current_version_id
   OR NEW.created_at < w.changed_at OR NEW.state <> 'pending' OR NEW.attempt_count <> 0
   OR NEW.active_token IS NOT NULL OR NEW.lease_until IS NOT NULL
   OR NEW.late IS DISTINCT FROM (NEW.created_at > NEW.intended_at)
   OR (NEW.kind = 'daily_review' AND NEW.identity_key <> 'daily_review:' || NEW.local_date::text) THEN
   RAISE EXCEPTION 'slot must begin pending with exact watch scope and honest lateness' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_scheduling_slotlease' THEN
  SELECT * INTO s FROM macro_scheduling_scheduledslot WHERE id = NEW.slot_id;
  SELECT * INTO v FROM macro_scheduling_watchversion WHERE id = s.watch_version_id;
  IF NEW.sequence <> s.attempt_count + 1 OR NEW.admitted_at < s.created_at
   OR s.state NOT IN ('pending', 'running')
   OR NEW.deadline_at IS DISTINCT FROM NEW.admitted_at + (v.configuration->>'lease_seconds')::integer * interval '1 second'
   OR (NEW.mode = 'recover') IS DISTINCT FROM EXISTS (SELECT 1 FROM macro_scheduling_analysisdispatch WHERE slot_id = s.id) THEN
   RAISE EXCEPTION 'lease scope/time/mode mismatch' USING ERRCODE = '23514';
  END IF;
  IF s.state = 'running' AND (s.lease_until > NEW.admitted_at OR NOT EXISTS
    (SELECT 1 FROM macro_scheduling_slotoutcome WHERE lease_id = s.active_token AND status = 'expired')) THEN
   RAISE EXCEPTION 'live lease cannot be replaced without expired outcome' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_scheduling_slotoutcome' THEN
  SELECT * INTO l FROM macro_scheduling_slotlease WHERE token = NEW.lease_id;
  SELECT * INTO s FROM macro_scheduling_scheduledslot WHERE id = l.slot_id;
  IF s.state <> 'running' OR s.active_token IS DISTINCT FROM l.token OR NEW.finished_at < l.admitted_at
   OR jsonb_typeof(NEW.payload) <> 'object'
   OR (NEW.status = 'expired' AND NEW.finished_at < l.deadline_at)
   OR (NEW.status <> 'expired' AND NEW.finished_at >= l.deadline_at) THEN
   RAISE EXCEPTION 'outcome must preserve the protected active lease ordering' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_scheduling_analysisdispatch' THEN
  SELECT * INTO s FROM macro_scheduling_scheduledslot WHERE id = NEW.slot_id;
  SELECT * INTO l FROM macro_scheduling_slotlease WHERE token = NEW.lease_id;
  SELECT * INTO v FROM macro_scheduling_watchversion WHERE id = s.watch_version_id;
  IF s.kind <> 'analysis' OR s.state <> 'running' OR s.active_token IS DISTINCT FROM l.token
   OR l.slot_id IS DISTINCT FROM s.id OR l.mode <> 'execute'
   OR NEW.started_at < l.admitted_at OR NEW.started_at >= l.deadline_at
   OR jsonb_typeof(NEW.request) <> 'object'
   OR NEW.request->>'expected_approval_id' IS DISTINCT FROM v.configuration->>'approval_id'
   OR NEW.request->>'expected_exposure_digest' IS DISTINCT FROM v.configuration->>'exposure_digest'
   OR NEW.request->>'provider' IS DISTINCT FROM v.configuration->>'provider'
   OR NEW.request->>'model_id' IS DISTINCT FROM v.configuration->>'model_id'
   OR NEW.request->'model_configuration' IS DISTINCT FROM v.configuration->'model_configuration'
   OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(v.configuration->'sources') source
      WHERE source->>'source_id' = NEW.request->>'source_id') THEN
   RAISE EXCEPTION 'analysis dispatch must bind its exact active lease and configured request' USING ERRCODE = '23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION schedule_state_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v macro_scheduling_watchversion; l macro_scheduling_slotlease; outcome varchar;
BEGIN
 IF TG_TABLE_NAME = 'macro_scheduling_watchrecord' THEN
  SELECT * INTO v FROM macro_scheduling_watchversion WHERE id = NEW.current_version_id;
  IF NEW.id <> OLD.id OR NEW.owner_id <> OLD.owner_id OR NEW.thesis_id <> OLD.thesis_id
   OR NEW.changed_at < OLD.changed_at OR NEW.next_capture_at < OLD.next_capture_at
   OR NEW.next_analysis_at < OLD.next_analysis_at OR NEW.next_daily_date < OLD.next_daily_date
   OR NEW.revision < OLD.revision OR NEW.revision > OLD.revision + 1
   OR v.watch_id IS DISTINCT FROM NEW.id OR v.sequence IS DISTINCT FROM NEW.revision
   OR (NEW.revision = OLD.revision AND NEW.current_version_id IS DISTINCT FROM OLD.current_version_id)
   OR (NEW.revision = OLD.revision + 1 AND (NEW.current_version_id IS NOT DISTINCT FROM OLD.current_version_id
       OR v.created_at IS DISTINCT FROM NEW.changed_at)) THEN
   RAISE EXCEPTION 'invalid watch state or cursor transition' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_scheduling_scheduledslot' THEN
  IF (to_jsonb(NEW) - ARRAY['state','attempt_count','active_token','lease_until']) IS DISTINCT FROM
     (to_jsonb(OLD) - ARRAY['state','attempt_count','active_token','lease_until'])
   OR OLD.state IN ('completed', 'blocked') THEN
   RAISE EXCEPTION 'slot identity/input and terminal state are immutable' USING ERRCODE = '23514';
  END IF;
  IF NEW.state = 'running' THEN
   SELECT * INTO l FROM macro_scheduling_slotlease WHERE token = NEW.active_token;
   IF l.slot_id IS DISTINCT FROM NEW.id OR l.sequence IS DISTINCT FROM NEW.attempt_count
    OR l.deadline_at IS DISTINCT FROM NEW.lease_until OR NEW.attempt_count <> OLD.attempt_count + 1 THEN
    RAISE EXCEPTION 'slot running state requires its exact new lease' USING ERRCODE = '23514';
   END IF;
  ELSIF NEW.state IN ('completed', 'blocked') THEN
   SELECT status INTO outcome FROM macro_scheduling_slotoutcome WHERE lease_id = OLD.active_token;
   IF OLD.state <> 'running' OR NEW.attempt_count <> OLD.attempt_count OR outcome IS NULL
    OR outcome = 'expired' OR (NEW.state = 'completed') IS DISTINCT FROM (outcome = 'completed') THEN
    RAISE EXCEPTION 'slot terminal state requires the matching retained outcome' USING ERRCODE = '23514';
   END IF;
  ELSE
   RAISE EXCEPTION 'slot cannot return to pending' USING ERRCODE = '23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
"""
SQL += "\n".join(f"CREATE TRIGGER schedule_{table}_immutable BEFORE UPDATE OR DELETE ON macro_scheduling_{table} FOR EACH ROW EXECUTE FUNCTION schedule_immutable();" for table in IMMUTABLE)
SQL += "\n" + "\n".join(f"CREATE TRIGGER schedule_{table}_insert BEFORE INSERT ON macro_scheduling_{table} FOR EACH ROW EXECUTE FUNCTION schedule_insert_guard();" for table in ("watchrecord", "watchversion", "scheduledslot", "slotlease", "slotoutcome", "analysisdispatch"))
SQL += "\n" + "\n".join(f"CREATE TRIGGER schedule_{table}_state BEFORE UPDATE ON macro_scheduling_{table} FOR EACH ROW EXECUTE FUNCTION schedule_state_guard();" for table in ("watchrecord", "scheduledslot"))
SQL += "\n" + "\n".join(f"CREATE TRIGGER schedule_{table}_delete BEFORE DELETE ON macro_scheduling_{table} FOR EACH ROW EXECUTE FUNCTION schedule_immutable();" for table in ("watchrecord", "scheduledslot"))

REVERSE = "\n".join(f"DROP TRIGGER schedule_{table}_immutable ON macro_scheduling_{table};" for table in IMMUTABLE)
REVERSE += "\n" + "\n".join(f"DROP TRIGGER schedule_{table}_insert ON macro_scheduling_{table};" for table in ("watchrecord", "watchversion", "scheduledslot", "slotlease", "slotoutcome", "analysisdispatch"))
REVERSE += "\n" + "\n".join(f"DROP TRIGGER schedule_{table}_state ON macro_scheduling_{table};" for table in ("watchrecord", "scheduledslot"))
REVERSE += "\n" + "\n".join(f"DROP TRIGGER schedule_{table}_delete ON macro_scheduling_{table};" for table in ("watchrecord", "scheduledslot"))
REVERSE += "\nDROP FUNCTION schedule_insert_guard(); DROP FUNCTION schedule_state_guard(); DROP FUNCTION schedule_immutable();"


class Migration(migrations.Migration):
    dependencies = [("macro_scheduling", "0002_scheduledslot_schedule_due_owner_kind_and_more")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
