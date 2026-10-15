"""Admit an explicit new research profile without rewriting retained admissions."""

from django.db import migrations


def guard(profiles):
    return """
CREATE OR REPLACE FUNCTION macro_compile_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE packet macro_desk_researchevidencecontext%ROWTYPE;
BEGIN
 IF NEW.evidence_context_id IS NULL THEN
  IF NEW.configuration->>'context'='retained_source_evidence'
   OR NEW.configuration->>'schema_version' IN ('source-backed-thesis-compilation-v1','source-backed-thesis-compilation-v2')
   OR NEW.configuration->>'prompt_version' IN ('source-backed-thesis-prompt-v1','source-backed-thesis-prompt-v2') THEN
   RAISE EXCEPTION 'source compilation requires retained evidence' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO STRICT packet FROM macro_desk_researchevidencecontext WHERE id=NEW.evidence_context_id;
  IF packet.created_at>NEW.created_at OR NEW.configuration->>'context' IS DISTINCT FROM 'retained_source_evidence'
   OR jsonb_build_array(NEW.configuration->>'schema_version',NEW.configuration->>'prompt_version')
      NOT IN (""" + profiles + """) THEN
   RAISE EXCEPTION 'source compilation context or admission mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
"""


LEGACY = """'["source-backed-thesis-compilation-v1","source-backed-thesis-prompt-v1"]'::jsonb"""
RESEARCH = """'["source-backed-thesis-compilation-v2","source-backed-thesis-prompt-v2"]'::jsonb"""


class Migration(migrations.Migration):
    dependencies = [("macro_theses", "0004_compilation_evidence")]
    operations = [migrations.RunSQL(guard(LEGACY + "," + RESEARCH), guard(LEGACY))]
