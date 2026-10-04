"""Protect stable identities and monotonic progress on mutable state records.

These guards do not authenticate callers or acquire row locks. Every service
still locks the brief first, then applies domain rules within its transaction.
"""

from django.db import migrations


GUARDS_SQL = """
CREATE FUNCTION macro_agent_guard_notification_lifecycle() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'notification intent cannot be deleted' USING ERRCODE = '23514';
    END IF;
    IF ROW(NEW.intent_id, NEW.brief_id, NEW.assessment_id, NEW.created_at)
       IS DISTINCT FROM ROW(OLD.intent_id, OLD.brief_id, OLD.assessment_id, OLD.created_at) THEN
        RAISE EXCEPTION 'notification intent identity is immutable' USING ERRCODE = '23514';
    END IF;
    IF OLD.state <> 'pending' AND NEW.state IS DISTINCT FROM OLD.state THEN
        RAISE EXCEPTION 'terminal notification state cannot change' USING ERRCODE = '23514';
    END IF;
    IF NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'notification timestamp cannot move backwards' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER macro_notification_lifecycle_guard
BEFORE UPDATE OR DELETE ON macro_notification_intents
FOR EACH ROW EXECUTE FUNCTION macro_agent_guard_notification_lifecycle();

CREATE FUNCTION macro_agent_guard_head_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'governing dependency head cannot be deleted' USING ERRCODE = '23514';
    END IF;
    IF ROW(NEW.id, NEW.brief_id, NEW.role) IS DISTINCT FROM ROW(OLD.id, OLD.brief_id, OLD.role) THEN
        RAISE EXCEPTION 'dependency head identity is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER macro_dependency_head_identity_guard
BEFORE UPDATE OR DELETE ON macro_dependency_heads
FOR EACH ROW EXECUTE FUNCTION macro_agent_guard_head_identity();

CREATE FUNCTION macro_agent_guard_pointer_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.brief_id IS DISTINCT FROM OLD.brief_id THEN
        RAISE EXCEPTION 'current assessment brief identity is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER macro_current_pointer_identity_guard
BEFORE UPDATE ON macro_current_assessments
FOR EACH ROW EXECUTE FUNCTION macro_agent_guard_pointer_identity();

CREATE FUNCTION macro_agent_guard_reassessment_lifecycle() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'reassessment work cannot be deleted' USING ERRCODE = '23514';
    END IF;
    IF ROW(NEW.id, NEW.brief_id, NEW.context_digest, NEW.reason, NEW.created_at)
       IS DISTINCT FROM ROW(OLD.id, OLD.brief_id, OLD.context_digest, OLD.reason, OLD.created_at) THEN
        RAISE EXCEPTION 'reassessment work identity is immutable' USING ERRCODE = '23514';
    END IF;
    IF OLD.state <> 'pending' AND (
       NEW.state IS DISTINCT FROM OLD.state OR NEW.completed_at IS DISTINCT FROM OLD.completed_at) THEN
        RAISE EXCEPTION 'terminal reassessment work cannot change' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER macro_reassessment_lifecycle_guard
BEFORE UPDATE OR DELETE ON macro_reassessment_work
FOR EACH ROW EXECUTE FUNCTION macro_agent_guard_reassessment_lifecycle();

CREATE FUNCTION macro_agent_guard_brief_progression() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.generation < OLD.generation THEN
        RAISE EXCEPTION 'brief generation cannot move backwards' USING ERRCODE = '23514';
    END IF;
    IF NEW.changed_at < OLD.changed_at THEN
        RAISE EXCEPTION 'brief changed_at cannot move backwards' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER macro_brief_progression_guard
BEFORE UPDATE ON macro_brief_states
FOR EACH ROW EXECUTE FUNCTION macro_agent_guard_brief_progression();
"""

REVERSE_GUARDS_SQL = """
DROP TRIGGER macro_brief_progression_guard ON macro_brief_states;
DROP FUNCTION macro_agent_guard_brief_progression();
DROP TRIGGER macro_reassessment_lifecycle_guard ON macro_reassessment_work;
DROP FUNCTION macro_agent_guard_reassessment_lifecycle();
DROP TRIGGER macro_current_pointer_identity_guard ON macro_current_assessments;
DROP FUNCTION macro_agent_guard_pointer_identity();
DROP TRIGGER macro_dependency_head_identity_guard ON macro_dependency_heads;
DROP FUNCTION macro_agent_guard_head_identity();
DROP TRIGGER macro_notification_lifecycle_guard ON macro_notification_intents;
DROP FUNCTION macro_agent_guard_notification_lifecycle();
"""


class Migration(migrations.Migration):
    dependencies = [("macro_persistence", "0001_initial")]
    operations = [migrations.RunSQL(sql=GUARDS_SQL, reverse_sql=REVERSE_GUARDS_SQL)]
