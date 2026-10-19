"""Retain exact scoped question context without rewriting legacy packets."""

from importlib import import_module
from django.db import migrations


LEGACY_SHAPE = r"""
CREATE OR REPLACE FUNCTION desk_research_context_shape() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF jsonb_typeof(NEW.content) IS DISTINCT FROM 'object'
  OR NEW.content->>'schema_version' IS DISTINCT FROM 'retained-source-evidence-v1'
  OR jsonb_typeof(NEW.content->'reports') IS DISTINCT FROM 'array'
  OR jsonb_array_length(NEW.content->'reports') NOT BETWEEN 1 AND 16
  OR (NEW.content->>'cutoff')::timestamptz IS DISTINCT FROM NEW.created_at
  OR octet_length(NEW.content::text)>131072 THEN
  RAISE EXCEPTION 'research evidence requires bounded exact inputs' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
"""


SQL = r"""
CREATE OR REPLACE FUNCTION desk_research_context_shape() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE context jsonb; node jsonb; index integer; report_ids jsonb; query_ids jsonb;
 r macro_desk_researchrun%ROWTYPE; p macro_desk_researchplanattempt%ROWTYPE;
 plan macro_desk_researchplanresult%ROWTYPE;
 d macro_desk_researchdiscoveryattempt%ROWTYPE;
 receipt macro_desk_researchdiscoveryreceipt%ROWTYPE;
 result macro_desk_researchdiscoveryresult%ROWTYPE;
 contract macro_desk_sourcecontractversion%ROWTYPE;
BEGIN
 IF jsonb_typeof(NEW.content) IS DISTINCT FROM 'object'
  OR NOT coalesce(NEW.content->>'schema_version' IN ('retained-source-evidence-v1','retained-source-evidence-v2'),false)
  OR jsonb_typeof(NEW.content->'reports') IS DISTINCT FROM 'array'
  OR jsonb_array_length(NEW.content->'reports') NOT BETWEEN 1 AND 16
  OR (NEW.content->>'cutoff')::timestamptz IS DISTINCT FROM NEW.created_at
  OR octet_length(NEW.content::text)>131072 THEN
  RAISE EXCEPTION 'research evidence requires bounded exact inputs' USING ERRCODE='23514';
 END IF;
 IF NEW.content->>'schema_version'='retained-source-evidence-v1' THEN
  IF NEW.content ? 'question_research' THEN
   RAISE EXCEPTION 'legacy evidence cannot acquire question context' USING ERRCODE='23514';
  END IF;
 ELSE
  context := NEW.content->'question_research';
  IF jsonb_typeof(context) IS DISTINCT FROM 'object'
   OR context->>'schema_version' IS DISTINCT FROM 'question-research-context-v1'
   OR jsonb_typeof(context->'questions') IS DISTINCT FROM 'array'
   OR jsonb_array_length(context->'questions') NOT BETWEEN 1 AND 3
   OR context->'coverage_complete' IS DISTINCT FROM 'false'::jsonb
   OR context->>'evidence_depth' IS DISTINCT FROM 'headline_metadata_only' THEN
   RAISE EXCEPTION 'question context requires a bounded labelled investigation' USING ERRCODE='23514';
  END IF;
  SELECT * INTO r FROM macro_desk_researchrun WHERE id=(context->>'run_id')::uuid;
  SELECT * INTO p FROM macro_desk_researchplanattempt WHERE id=(context->>'plan_attempt_id')::uuid;
  SELECT * INTO plan FROM macro_desk_researchplanresult WHERE attempt_id=p.id;
  IF r.id IS NULL OR r.owner_id IS DISTINCT FROM NEW.owner_id OR r.thesis_id IS DISTINCT FROM NEW.thesis_id
   OR p.id IS NULL OR p.run_id IS DISTINCT FROM r.id OR p.owner_id IS DISTINCT FROM NEW.owner_id
   OR p.thesis_id IS DISTINCT FROM NEW.thesis_id OR plan.status IS DISTINCT FROM 'planned'
   OR context->>'run_request_digest' IS DISTINCT FROM r.request_digest
   OR context->>'exact_question_digest' IS DISTINCT FROM encode(sha256(convert_to(r.exact_question,'UTF8')),'hex')
   OR context->>'plan_prompt_digest' IS DISTINCT FROM p.prompt_digest
   OR context->>'plan_result_id' IS DISTINCT FROM p.id::text
   OR NOT coalesce(context->>'plan_result_digest' ~ '^[0-9a-f]{64}$',false)
   OR r.created_at>NEW.created_at OR p.created_at>NEW.created_at OR plan.finished_at>NEW.created_at
   OR jsonb_array_length(context->'questions') IS DISTINCT FROM jsonb_array_length(plan.document->'questions')
   OR jsonb_array_length(context->'questions') IS DISTINCT FROM
       (SELECT count(*)::integer FROM macro_desk_researchdiscoveryattempt WHERE run_id=r.id) THEN
   RAISE EXCEPTION 'question context requires exact private run and plan' USING ERRCODE='23514';
  END IF;
  index := 0;
  FOR node IN SELECT value FROM jsonb_array_elements(context->'questions') LOOP
   SELECT * INTO d FROM macro_desk_researchdiscoveryattempt WHERE id=(node->>'discovery_attempt_id')::uuid;
   SELECT * INTO receipt FROM macro_desk_researchdiscoveryreceipt WHERE attempt_id=d.id;
   SELECT * INTO result FROM macro_desk_researchdiscoveryresult WHERE attempt_id=d.id;
   SELECT * INTO contract FROM macro_desk_sourcecontractversion WHERE id=(node->>'contract_version_id')::uuid;
   IF d.id IS NULL OR d.run_id IS DISTINCT FROM r.id OR d.question_index IS DISTINCT FROM index
    OR node->'question_index' IS DISTINCT FROM to_jsonb(index)
    OR node->'planned_question' IS DISTINCT FROM plan.document->'questions'->index
    OR d.question IS DISTINCT FROM node->'planned_question'
    OR node->>'source_id' IS DISTINCT FROM d.source_id
    OR receipt.attempt_id IS NULL OR result.attempt_id IS NULL
    OR contract.id IS NULL OR contract.source_id IS DISTINCT FROM d.source_id
    OR contract.digest IS DISTINCT FROM node->>'contract_digest'
    OR contract.contract IS DISTINCT FROM d.contract OR NOT contract.permitted
    OR contract.observed_at>NEW.created_at
    OR NOT EXISTS (SELECT 1 FROM macro_desk_sourcecontracthead h WHERE h.source_id=d.source_id AND h.version_id=contract.id)
    OR node->>'receipt_id' IS DISTINCT FROM d.id::text OR node->>'result_id' IS DISTINCT FROM d.id::text
    OR NOT coalesce(node->>'receipt_digest' ~ '^[0-9a-f]{64}$',false)
    OR NOT coalesce(node->>'result_digest' ~ '^[0-9a-f]{64}$',false)
    OR result.status IS DISTINCT FROM 'captured' OR node->>'status' IS DISTINCT FROM 'captured'
    OR result.capture_id IS DISTINCT FROM receipt.capture_id
    OR node->>'capture_id' IS DISTINCT FROM receipt.capture_id::text
    OR result.metadata IS DISTINCT FROM receipt.metadata
    OR node->'revision_ids' IS DISTINCT FROM result.revision_ids
    OR node->'returned_candidate_count' IS DISTINCT FROM receipt.metadata->'returned_candidate_count'
    OR node->'selected_count' IS DISTINCT FROM receipt.metadata->'selected_count'
    OR node->'candidate_cap_reached' IS DISTINCT FROM receipt.metadata->'candidate_cap_reached'
    OR node->'excluded_count' IS DISTINCT FROM to_jsonb(
        jsonb_array_length(receipt.metadata->'candidates')-jsonb_array_length(result.revision_ids))
    OR node->'exclusion_counts' IS DISTINCT FROM (
        SELECT coalesce(jsonb_object_agg(reason,n),'{}'::jsonb) FROM (
          SELECT c->>'exclusion_reason' AS reason,count(*) AS n
          FROM jsonb_array_elements(receipt.metadata->'candidates') c
          WHERE c->'selected'='false'::jsonb GROUP BY c->>'exclusion_reason') counts)
    OR d.admitted_at>NEW.created_at OR receipt.received_at>NEW.created_at OR result.finished_at>NEW.created_at THEN
    RAISE EXCEPTION 'question context requires every exact captured node' USING ERRCODE='23514';
   END IF;
   index := index+1;
  END LOOP;
  SELECT jsonb_agg(value ORDER BY value) INTO report_ids FROM (
      SELECT report->>'revision_id' AS value FROM jsonb_array_elements(NEW.content->'reports') report) ids;
  SELECT jsonb_agg(value ORDER BY value) INTO query_ids FROM (
      SELECT DISTINCT revision #>> '{}' AS value FROM jsonb_array_elements(context->'questions') question,
        jsonb_array_elements(question->'revision_ids') revision) ids;
  IF report_ids IS DISTINCT FROM query_ids OR EXISTS (
    SELECT 1 FROM jsonb_array_elements(context->'questions') question,
      jsonb_array_elements_text(question->'revision_ids') revision
      JOIN macro_monitoring_sourcerevision v ON v.id=revision::uuid
      JOIN macro_monitoring_sourcereport report ON report.id=v.report_id
      WHERE report.source_id IS DISTINCT FROM question->>'source_id') THEN
   RAISE EXCEPTION 'question context requires its complete exact revision union' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION macro_compile_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE packet macro_desk_researchevidencecontext%ROWTYPE; suffix text;
BEGIN
 IF NEW.evidence_context_id IS NULL THEN
  IF NEW.configuration->>'context'='retained_source_evidence'
   OR NEW.configuration->>'schema_version' IN ('source-backed-thesis-compilation-v1','source-backed-thesis-compilation-v2')
   OR NEW.configuration->>'prompt_version' LIKE 'source-backed-thesis-prompt-%' THEN
   RAISE EXCEPTION 'source compilation requires retained evidence' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO STRICT packet FROM macro_desk_researchevidencecontext WHERE id=NEW.evidence_context_id;
  suffix := CASE WHEN packet.content ? 'question_research' THEN '-question-research-v1' ELSE '' END;
  IF packet.created_at>NEW.created_at OR NEW.configuration->>'context' IS DISTINCT FROM 'retained_source_evidence'
   OR NOT coalesce(((NEW.configuration->>'schema_version'='source-backed-thesis-compilation-v1'
            AND NEW.configuration->>'prompt_version'='source-backed-thesis-prompt-v1'||suffix)
       OR (NEW.configuration->>'schema_version'='source-backed-thesis-compilation-v2'
            AND NEW.configuration->>'prompt_version'='source-backed-thesis-prompt-v2'||suffix)),false) THEN
   RAISE EXCEPTION 'source compilation context or admission mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
"""

previous = import_module("macro_agent.theses.migrations.0005_driver_research_profile")
REVERSE = LEGACY_SHAPE + previous.guard(previous.LEGACY + "," + previous.RESEARCH)


class Migration(migrations.Migration):
    dependencies = [("macro_desk", "0008_question_led_research"),
                    ("macro_theses", "0005_driver_research_profile")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
