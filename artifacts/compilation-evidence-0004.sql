BEGIN;
--
-- Add field evidence_context to compilationattempt
--
ALTER TABLE "macro_compilation_attempts" ADD COLUMN "evidence_context_id" uuid NULL CONSTRAINT "macro_compilation_at_evidence_context_id_ace6bc80_fk_macro_des" REFERENCES "macro_desk_researchevidencecontext"("id") DEFERRABLE INITIALLY DEFERRED; SET CONSTRAINTS "macro_compilation_at_evidence_context_id_ace6bc80_fk_macro_des" IMMEDIATE;
--
-- Raw SQL operation
--

ALTER TABLE macro_compilation_attempts ADD CONSTRAINT macro_compile_evidence_scope_fk
 FOREIGN KEY(evidence_context_id,owner_id,thesis_id)
 REFERENCES macro_desk_researchevidencecontext(id,owner_id,thesis_id) DEFERRABLE INITIALLY IMMEDIATE;
CREATE FUNCTION macro_compile_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE packet macro_desk_researchevidencecontext%ROWTYPE;
BEGIN
 IF NEW.evidence_context_id IS NULL THEN
  IF NEW.configuration->>'context'='retained_source_evidence' THEN
   RAISE EXCEPTION 'source compilation requires retained evidence' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO STRICT packet FROM macro_desk_researchevidencecontext WHERE id=NEW.evidence_context_id;
  IF packet.created_at>NEW.created_at OR NEW.configuration->>'context' IS DISTINCT FROM 'retained_source_evidence'
   OR NEW.configuration->>'schema_version' IS DISTINCT FROM 'source-backed-thesis-compilation-v1'
   OR NEW.configuration->>'prompt_version' IS DISTINCT FROM 'source-backed-thesis-prompt-v1' THEN
   RAISE EXCEPTION 'source compilation context or admission mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER macro_compile_evidence_guard BEFORE INSERT ON macro_compilation_attempts
 FOR EACH ROW EXECUTE FUNCTION macro_compile_evidence_guard();

CREATE INDEX "macro_compilation_attempts_evidence_context_id_ace6bc80" ON "macro_compilation_attempts" ("evidence_context_id");
COMMIT;
