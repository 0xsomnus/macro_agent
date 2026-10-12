BEGIN;
--
-- Create model DailySynthesisAttempt
--
CREATE TABLE "macro_desk_dailysynthesisattempt" ("id" uuid NOT NULL PRIMARY KEY, "command_id" uuid NOT NULL, "request_digest" varchar(64) NOT NULL, "review_digest" varchar(64) NOT NULL, "context" jsonb NOT NULL, "context_digest" varchar(64) NOT NULL, "provider" varchar(32) NOT NULL, "model_id" varchar(255) NOT NULL, "model_metadata" jsonb NOT NULL, "configuration" jsonb NOT NULL, "created_at" timestamp with time zone NOT NULL, "deadline_at" timestamp with time zone NOT NULL, "owner_id" uuid NOT NULL, "thesis_id" uuid NOT NULL, "review_id" uuid NOT NULL, CONSTRAINT "desk_synthesis_command_once" UNIQUE ("owner_id", "command_id"), CONSTRAINT "desk_synthesis_deadline" CHECK ("deadline_at" > ("created_at")));
--
-- Create model DailySynthesisResult
--
CREATE TABLE "macro_desk_dailysynthesisresult" ("attempt_id" uuid NOT NULL PRIMARY KEY, "status" varchar(32) NOT NULL, "document" jsonb NULL, "provider_metadata" jsonb NOT NULL, "stop_reason" varchar(64) NOT NULL, "stale_reasons" jsonb NOT NULL, "finished_at" timestamp with time zone NOT NULL, CONSTRAINT "desk_synthesis_result_status" CHECK ("status" IN ('synthesised', 'stale', 'failed', 'outcome_unknown')), CONSTRAINT "desk_synthesis_document_present" CHECK ((NOT ("status" IN ('synthesised', 'stale')) OR "document" IS NOT NULL)));
--
-- Raw SQL operation
--

CREATE FUNCTION desk_synthesis_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r macro_desk_dailyreview%ROWTYPE; a macro_desk_dailysynthesisattempt%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME='macro_desk_dailysynthesisattempt' THEN
  SELECT * INTO r FROM macro_desk_dailyreview WHERE id=NEW.review_id;
  IF r.id IS NULL OR r.owner_id IS DISTINCT FROM NEW.owner_id
   OR r.thesis_id IS DISTINCT FROM NEW.thesis_id OR r.digest IS DISTINCT FROM NEW.review_digest
   OR NEW.created_at<r.prepared_at OR NEW.context->>'review_id' IS DISTINCT FROM r.id::text
   OR NEW.context->>'review_digest' IS DISTINCT FROM r.digest
   OR NEW.context->'review' IS DISTINCT FROM r.content
   OR NEW.context->'original_inputs' IS DISTINCT FROM (SELECT resolved_inputs FROM macro_desk_privatecontext WHERE id=r.context_id)
   OR NEW.context->'report_heads' IS DISTINCT FROM (
       SELECT coalesce(jsonb_object_agg(v.report_id::text,to_jsonb(er.head_at_preparation_id::text)), '{}'::jsonb)
       FROM macro_desk_evidencerevision er JOIN macro_monitoring_sourcerevision v ON v.id=er.revision_id
       WHERE er.evidence_id=(SELECT evidence_id FROM macro_desk_privatecontext WHERE id=r.context_id))
   OR jsonb_typeof(NEW.context->'report_heads') IS DISTINCT FROM 'object'
   OR NEW.request_digest !~ '^[0-9a-f]{64}$' OR NEW.context_digest !~ '^[0-9a-f]{64}$'
   OR NOT desk_daily_context_current(r.context_id)
   OR jsonb_typeof(NEW.configuration) IS DISTINCT FROM 'object'
   OR jsonb_typeof(NEW.model_metadata) IS DISTINCT FROM 'object' THEN
   RAISE EXCEPTION 'synthesis admission requires exact scoped retained review' USING ERRCODE='23514';
  END IF;
 ELSE
  SELECT * INTO a FROM macro_desk_dailysynthesisattempt WHERE id=NEW.attempt_id;
  IF a.id IS NULL OR NEW.finished_at<a.created_at
   OR jsonb_typeof(NEW.provider_metadata) IS DISTINCT FROM 'object'
   OR jsonb_typeof(NEW.stale_reasons) IS DISTINCT FROM 'array'
   OR (NEW.document IS NOT NULL AND jsonb_typeof(NEW.document)<>'object')
   OR (NEW.status='stale' AND jsonb_array_length(NEW.stale_reasons)=0)
   OR (NEW.status='synthesised' AND (jsonb_array_length(NEW.stale_reasons)<>0
       OR NEW.finished_at>=a.deadline_at
       OR NOT desk_daily_context_current((SELECT context_id FROM macro_desk_dailyreview WHERE id=a.review_id)))) THEN
   RAISE EXCEPTION 'synthesis result requires valid original scoped disposition' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER desk_synthesis_attempt_scope BEFORE INSERT ON macro_desk_dailysynthesisattempt
 FOR EACH ROW EXECUTE FUNCTION desk_synthesis_scope_guard();
CREATE TRIGGER desk_synthesis_result_scope BEFORE INSERT ON macro_desk_dailysynthesisresult
 FOR EACH ROW EXECUTE FUNCTION desk_synthesis_scope_guard();
CREATE TRIGGER desk_synthesis_attempt_immutable BEFORE UPDATE OR DELETE ON macro_desk_dailysynthesisattempt
 FOR EACH ROW EXECUTE FUNCTION desk_reject_change();
CREATE TRIGGER desk_synthesis_result_immutable BEFORE UPDATE OR DELETE ON macro_desk_dailysynthesisresult
 FOR EACH ROW EXECUTE FUNCTION desk_reject_change();

ALTER TABLE "macro_desk_dailysynthesisattempt" ADD CONSTRAINT "macro_desk_dailysynt_owner_id_81b0dede_fk_macro_web" FOREIGN KEY ("owner_id") REFERENCES "macro_web_user" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "macro_desk_dailysynthesisattempt" ADD CONSTRAINT "macro_desk_dailysynt_thesis_id_54eb2939_fk_macro_the" FOREIGN KEY ("thesis_id") REFERENCES "macro_theses" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "macro_desk_dailysynthesisattempt" ADD CONSTRAINT "macro_desk_dailysynt_review_id_f047d7fc_fk_macro_des" FOREIGN KEY ("review_id") REFERENCES "macro_desk_dailyreview" ("id") DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX "macro_desk_dailysynthesisattempt_owner_id_81b0dede" ON "macro_desk_dailysynthesisattempt" ("owner_id");
CREATE INDEX "macro_desk_dailysynthesisattempt_thesis_id_54eb2939" ON "macro_desk_dailysynthesisattempt" ("thesis_id");
CREATE INDEX "macro_desk_dailysynthesisattempt_review_id_f047d7fc" ON "macro_desk_dailysynthesisattempt" ("review_id");
ALTER TABLE "macro_desk_dailysynthesisresult" ADD CONSTRAINT "macro_desk_dailysynt_attempt_id_f7a8cdaa_fk_macro_des" FOREIGN KEY ("attempt_id") REFERENCES "macro_desk_dailysynthesisattempt" ("id") DEFERRABLE INITIALLY DEFERRED;
COMMIT;
