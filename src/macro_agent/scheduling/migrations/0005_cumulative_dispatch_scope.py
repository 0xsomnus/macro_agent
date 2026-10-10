from django.db import migrations


SQL = """
CREATE FUNCTION schedule_context_dispatch_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
 s macro_scheduling_scheduledslot;
 l macro_scheduling_slotlease;
 r macro_scheduling_slotrecovery;
 v macro_scheduling_watchversion;
 expected_sources jsonb;
 mode text;
BEGIN
 SELECT * INTO s FROM macro_scheduling_scheduledslot WHERE id = NEW.slot_id;
 SELECT * INTO l FROM macro_scheduling_slotlease WHERE token = NEW.lease_id;
 IF l.recovery_id IS NULL THEN
  SELECT * INTO v FROM macro_scheduling_watchversion WHERE id = s.watch_version_id;
 ELSE
  SELECT * INTO r FROM macro_scheduling_slotrecovery WHERE id = l.recovery_id;
  SELECT * INTO v FROM macro_scheduling_watchversion WHERE id = r.watch_version_id;
 END IF;
 mode := v.configuration->'model_configuration'->>'context';
 IF jsonb_typeof(NEW.request) IS DISTINCT FROM 'object'
  OR NOT (NEW.request ?& ARRAY['source_id', 'expected_approval_id',
      'expected_exposure_digest', 'provider', 'model_id', 'model_configuration']) THEN
  RAISE EXCEPTION 'analysis dispatch requires its exact reviewed request shape' USING ERRCODE = '23514';
 END IF;
 IF mode = 'complete_retained_context' THEN
  SELECT jsonb_agg(source->'source_id' ORDER BY ordinal) INTO expected_sources
   FROM jsonb_array_elements(v.configuration->'sources') WITH ORDINALITY AS sources(source, ordinal);
  IF (SELECT count(*) FROM jsonb_object_keys(NEW.request)) <> 8
   OR NOT (NEW.request ?& ARRAY['context_source_ids', 'context_bounds'])
   OR NEW.request->'context_source_ids' IS DISTINCT FROM expected_sources
   OR (NEW.request->'context_bounds')::text IS DISTINCT FROM (v.configuration->'context_bounds')::text THEN
   RAISE EXCEPTION 'cumulative dispatch must retain its complete reviewed source scope and bounds' USING ERRCODE = '23514';
  END IF;
 ELSIF mode = 'one_retained_report_and_approved_paper_book' THEN
  IF (SELECT count(*) FROM jsonb_object_keys(NEW.request)) <> 6 THEN
   RAISE EXCEPTION 'legacy dispatch cannot acquire unreviewed cumulative inputs' USING ERRCODE = '23514';
  END IF;
 ELSE
  RAISE EXCEPTION 'analysis dispatch requires a supported reviewed context mode' USING ERRCODE = '23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER schedule_context_dispatch_insert BEFORE INSERT ON macro_scheduling_analysisdispatch
 FOR EACH ROW EXECUTE FUNCTION schedule_context_dispatch_guard();
"""

REVERSE = """
DROP TRIGGER schedule_context_dispatch_insert ON macro_scheduling_analysisdispatch;
DROP FUNCTION schedule_context_dispatch_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("macro_scheduling", "0004_slotrecovery_slotlease_recovery")]

    operations = [migrations.RunSQL(SQL, REVERSE)]
