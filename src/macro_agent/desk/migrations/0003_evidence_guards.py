"""Immutable context, relational scope and non-reactivating permission lineage."""

from django.db import migrations


TABLES = ("sourcecontractversion", "analysisresultobservation", "evidenceset", "evidencesource",
          "evidencerevision", "evidenceanalysis", "privatecontext", "dailyreview")
SQL = """
CREATE FUNCTION desk_reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'desk evidence is immutable' USING ERRCODE = '23514'; END $$;
ALTER TABLE macro_desk_evidenceset ADD CONSTRAINT desk_evidence_owner_fk
 FOREIGN KEY (thesis_id, owner_id) REFERENCES macro_theses(id, owner_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_desk_privatecontext ADD CONSTRAINT desk_context_owner_fk
 FOREIGN KEY (thesis_id, owner_id) REFERENCES macro_theses(id, owner_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_desk_privatecontext ADD CONSTRAINT desk_context_evidence_scope_fk
 FOREIGN KEY (evidence_id, owner_id, thesis_id) REFERENCES macro_desk_evidenceset(id, owner_id, thesis_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_desk_privatecontext ADD CONSTRAINT desk_context_predecessor_scope_fk
 FOREIGN KEY (predecessor_id, owner_id, thesis_id) REFERENCES macro_desk_privatecontext(id, owner_id, thesis_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_desk_privatecontext ADD CONSTRAINT desk_context_approval_scope_fk
 FOREIGN KEY (thesis_id, approval_id) REFERENCES macro_thesis_approvals(thesis_id, id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_desk_dailyreview ADD CONSTRAINT desk_review_context_scope_fk
 FOREIGN KEY (context_id, owner_id, thesis_id) REFERENCES macro_desk_privatecontext(id, owner_id, thesis_id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_desk_evidencesource ADD CONSTRAINT desk_source_contract_scope_fk
 FOREIGN KEY (source_id, contract_id) REFERENCES macro_desk_sourcecontractversion(source_id, id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_desk_sourcecontracthead ADD CONSTRAINT desk_contract_head_scope_fk
 FOREIGN KEY (source_id, version_id) REFERENCES macro_desk_sourcecontractversion(source_id, id) DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_desk_sourcecontractversion ADD CONSTRAINT desk_contract_parent_scope_fk
 FOREIGN KEY (source_id, parent_id) REFERENCES macro_desk_sourcecontractversion(source_id, id) DEFERRABLE INITIALLY IMMEDIATE;

CREATE FUNCTION desk_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source varchar; contract_source varchar; digest varchar; content jsonb;
 actual_owner uuid; actual_thesis uuid; approval_id uuid; interpretation_id uuid;
 prepared timestamptz; available timestamptz; starts timestamptz; cutoff timestamptz;
 prior uuid; parent_time timestamptz; source_revision uuid; report bigint; other_report bigint;
BEGIN
 IF TG_TABLE_NAME = 'macro_desk_sourcecontractversion' THEN
  SELECT contract, contract_digest INTO content, digest FROM macro_monitoring_sourcestate WHERE id = NEW.source_id;
  IF NEW.contract IS DISTINCT FROM content OR NEW.digest IS DISTINCT FROM digest
   OR NEW.provenance NOT IN ('existing_allowlisted_adapter_manifest','explicit_staff_permission_review')
   OR length(trim(NEW.reason)) = 0 THEN
   RAISE EXCEPTION 'source snapshot cannot introduce new use or content' USING ERRCODE = '23514';
  END IF;
  IF NEW.parent_id IS NOT NULL THEN
   SELECT observed_at INTO parent_time FROM macro_desk_sourcecontractversion WHERE id = NEW.parent_id;
   IF parent_time IS NULL OR NEW.observed_at < parent_time OR NEW.parent_id = NEW.id THEN
    RAISE EXCEPTION 'invalid permission version lineage' USING ERRCODE = '23514';
   END IF;
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_desk_analysisresultobservation' THEN
  SELECT finished_at INTO available FROM macro_monitoring_newsanalysisresult WHERE attempt_id = NEW.result_id;
  IF available IS NULL OR NEW.observed_by_at < available OR NEW.method <> 'postcommit_read' THEN
   RAISE EXCEPTION 'invalid postcommit analysis witness' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_desk_evidenceset' THEN
  IF jsonb_typeof(NEW.limits) <> 'object' OR jsonb_typeof(NEW.source_manifest) <> 'array' THEN
   RAISE EXCEPTION 'evidence configuration requires exact JSON records' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_desk_evidencerevision' THEN
  SELECT r.source_id,v.report_id INTO source,report FROM macro_monitoring_sourcerevision v
   JOIN macro_monitoring_sourcereport r ON r.id=v.report_id WHERE v.id=NEW.revision_id;
  SELECT source_id INTO contract_source FROM macro_desk_sourcecontractversion WHERE id=NEW.contract_id;
  IF source IS DISTINCT FROM contract_source OR NOT EXISTS
   (SELECT 1 FROM macro_desk_evidencesource WHERE evidence_id=NEW.evidence_id AND source_id=source AND contract_id=NEW.contract_id)
   OR (NEW.witness_id IS NOT NULL AND NEW.witness_id <> NEW.revision_id) THEN
   RAISE EXCEPTION 'evidence revision/contract/witness scope mismatch' USING ERRCODE = '23514';
  END IF;
  IF NEW.head_at_preparation_id IS NOT NULL THEN
   SELECT report_id INTO other_report FROM macro_monitoring_sourcerevision WHERE id=NEW.head_at_preparation_id;
   IF report IS DISTINCT FROM other_report THEN
    RAISE EXCEPTION 'evidence head belongs to another report' USING ERRCODE = '23514';
   END IF;
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_desk_evidenceanalysis' THEN
  SELECT a.owner_id,a.thesis_id,a.source_revision_id INTO actual_owner,actual_thesis,source_revision
   FROM macro_monitoring_newsanalysisattempt a WHERE id=NEW.attempt_id;
  IF NOT EXISTS (SELECT 1 FROM macro_desk_evidenceset e WHERE e.id=NEW.evidence_id AND e.owner_id=actual_owner AND e.thesis_id=actual_thesis)
   OR NOT EXISTS (SELECT 1 FROM macro_desk_evidencerevision WHERE evidence_id=NEW.evidence_id AND revision_id=source_revision)
   OR (NEW.result_id IS NOT NULL AND NEW.result_id <> NEW.attempt_id)
   OR (NEW.witness_id IS NOT NULL AND (NEW.result_id IS NULL OR NEW.witness_id <> NEW.result_id)) THEN
   RAISE EXCEPTION 'private analysis membership scope mismatch' USING ERRCODE = '23514';
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_desk_privatecontext' THEN
  SELECT a.interpretation_id INTO interpretation_id FROM macro_thesis_approvals a WHERE id=NEW.approval_id;
  SELECT e.prepared_at,e.start INTO prepared,starts FROM macro_desk_evidenceset e WHERE id=NEW.evidence_id;
  IF interpretation_id IS DISTINCT FROM NEW.interpretation_id OR prepared IS DISTINCT FROM NEW.prepared_at
   OR NEW.exposure_digest !~ '^[0-9a-f]{64}$' OR jsonb_typeof(NEW.resolved_inputs) <> 'object' THEN
   RAISE EXCEPTION 'context approval/evidence mismatch' USING ERRCODE = '23514';
  END IF;
  IF NEW.predecessor_id IS NOT NULL THEN
   SELECT e.cutoff,c.prepared_at INTO cutoff,parent_time FROM macro_desk_privatecontext c
    JOIN macro_desk_evidenceset e ON e.id=c.evidence_id WHERE c.id=NEW.predecessor_id;
   IF cutoff IS DISTINCT FROM starts OR parent_time > NEW.prepared_at OR NEW.predecessor_id=NEW.id THEN
    RAISE EXCEPTION 'context predecessor is not the previous interval' USING ERRCODE = '23514';
   END IF;
  END IF;
 ELSIF TG_TABLE_NAME = 'macro_desk_dailyreview' THEN
  SELECT e.start,e.cutoff,e.prepared_at INTO starts,cutoff,prepared FROM macro_desk_privatecontext c
   JOIN macro_desk_evidenceset e ON e.id=c.evidence_id WHERE c.id=NEW.context_id;
  IF starts IS DISTINCT FROM NEW.start OR cutoff IS DISTINCT FROM NEW.cutoff OR prepared IS DISTINCT FROM NEW.prepared_at
   OR NEW.digest !~ '^[0-9a-f]{64}$' OR NEW.request_digest !~ '^[0-9a-f]{64}$' OR jsonb_typeof(NEW.content) <> 'object'
   OR EXISTS (SELECT 1 FROM macro_desk_dailyreview d WHERE d.thesis_id=NEW.thesis_id AND d.cutoff >= NEW.cutoff) THEN
   RAISE EXCEPTION 'daily review cannot replace a later retained interval' USING ERRCODE = '23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION desk_permission_head_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent uuid;
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'permission head cannot disappear' USING ERRCODE='23514';
 END IF;
 SELECT parent_id INTO parent FROM macro_desk_sourcecontractversion WHERE id=NEW.version_id;
 IF (TG_OP='INSERT' AND parent IS NOT NULL) OR
    (TG_OP='UPDATE' AND (NEW.source_id<>OLD.source_id OR parent IS DISTINCT FROM OLD.version_id OR NEW.version_id=OLD.version_id)) THEN
  RAISE EXCEPTION 'permission head requires a fresh descendant version' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER desk_permission_head BEFORE INSERT OR UPDATE OR DELETE ON macro_desk_sourcecontracthead
 FOR EACH ROW EXECUTE FUNCTION desk_permission_head_guard();
"""
for table in TABLES:
    SQL += f"\nCREATE TRIGGER desk_{table}_immutable BEFORE UPDATE OR DELETE ON macro_desk_{table} FOR EACH ROW EXECUTE FUNCTION desk_reject_change();"
    SQL += f"\nCREATE TRIGGER desk_{table}_scope BEFORE INSERT ON macro_desk_{table} FOR EACH ROW EXECUTE FUNCTION desk_insert_guard();"

REVERSE = "DROP TRIGGER desk_permission_head ON macro_desk_sourcecontracthead;\nDROP FUNCTION desk_permission_head_guard();\n"
for table in reversed(TABLES):
    REVERSE += f"DROP TRIGGER desk_{table}_scope ON macro_desk_{table};\nDROP TRIGGER desk_{table}_immutable ON macro_desk_{table};\n"
REVERSE += "DROP FUNCTION desk_insert_guard();\nDROP FUNCTION desk_reject_change();\n"
for table, name in (("sourcecontractversion","desk_contract_parent_scope_fk"), ("sourcecontracthead","desk_contract_head_scope_fk"),
                    ("evidencesource","desk_source_contract_scope_fk"), ("dailyreview","desk_review_context_scope_fk"),
                    ("privatecontext","desk_context_approval_scope_fk"), ("privatecontext","desk_context_predecessor_scope_fk"),
                    ("privatecontext","desk_context_evidence_scope_fk"), ("privatecontext","desk_context_owner_fk"),
                    ("evidenceset","desk_evidence_owner_fk")):
    REVERSE += f"ALTER TABLE macro_desk_{table} DROP CONSTRAINT {name};\n"


class Migration(migrations.Migration):
    dependencies = [("macro_desk", "0002_permission_lineage")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
