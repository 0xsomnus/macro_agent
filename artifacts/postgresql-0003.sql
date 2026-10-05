BEGIN;
--
-- Create constraint macro_brief_owner_target on model briefstaterecord
--
ALTER TABLE "macro_brief_states" ADD CONSTRAINT "macro_brief_owner_target" UNIQUE ("brief_id", "owner_id");
--
-- Create model ContextAdmission
--
CREATE TABLE "macro_context_admissions" ("id" uuid NOT NULL PRIMARY KEY, "exposure_digest" varchar(64) NOT NULL, "input_digest" varchar(64) NOT NULL, "input_observed_at" timestamp with time zone NOT NULL, "admission_effective_at" timestamp with time zone NOT NULL, "resolved_inputs" jsonb NOT NULL, "pins" jsonb NOT NULL, "approval_id" uuid NOT NULL, "brief_id" varchar(255) NOT NULL, "thesis_id" uuid NOT NULL, CONSTRAINT "macro_admission_context_identity" UNIQUE ("brief_id", "approval_id", "exposure_digest"), CONSTRAINT "macro_admission_exposure_digest" CHECK ("exposure_digest"::text ~ '^[0-9a-f]{64}$'), CONSTRAINT "macro_admission_input_digest" CHECK ("input_digest"::text ~ '^[0-9a-f]{64}$'), CONSTRAINT "macro_admission_time_order" CHECK ("admission_effective_at" >= ("input_observed_at")));
--
-- Create model ThesisBriefBinding
--
CREATE TABLE "macro_thesis_brief_bindings" ("brief_id" varchar(255) NOT NULL PRIMARY KEY, "created_at" timestamp with time zone NOT NULL, "status" varchar(16) NOT NULL, "admitted_exposure_digest" varchar(64) NULL, "observed_at" timestamp with time zone NULL, "admitted_approval_id" uuid NULL, "owner_id" uuid NOT NULL, "thesis_id" uuid NOT NULL, CONSTRAINT "macro_binding_thesis_target" UNIQUE ("brief_id", "thesis_id"), CONSTRAINT "macro_binding_status_allowed" CHECK ("status" IN ('pending', 'ready')), CONSTRAINT "macro_binding_ready_inputs" CHECK (("status" = 'pending' OR ("admitted_approval_id" IS NOT NULL AND "admitted_exposure_digest" IS NOT NULL AND "admitted_exposure_digest"::text ~ '^[0-9a-f]{64}$' AND "observed_at" IS NOT NULL AND "status" = 'ready'))), CONSTRAINT "macro_binding_observation_order" CHECK (("observed_at" IS NULL OR "observed_at" >= ("created_at"))));
--
-- Raw SQL operation
--

ALTER TABLE macro_thesis_brief_bindings ADD CONSTRAINT macro_binding_brief_owner_fk
 FOREIGN KEY (brief_id, owner_id) REFERENCES macro_brief_states (brief_id, owner_id)
 DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_thesis_brief_bindings ADD CONSTRAINT macro_binding_thesis_owner_fk
 FOREIGN KEY (thesis_id, owner_id) REFERENCES macro_theses (id, owner_id)
 DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_thesis_brief_bindings ADD CONSTRAINT macro_binding_approval_scope_fk
 FOREIGN KEY (thesis_id, admitted_approval_id) REFERENCES macro_thesis_approvals (thesis_id, id)
 DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_context_admissions ADD CONSTRAINT macro_admission_binding_scope_fk
 FOREIGN KEY (brief_id, thesis_id) REFERENCES macro_thesis_brief_bindings (brief_id, thesis_id)
 DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_context_admissions ADD CONSTRAINT macro_admission_approval_scope_fk
 FOREIGN KEY (thesis_id, approval_id) REFERENCES macro_thesis_approvals (thesis_id, id)
 DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_thesis_brief_bindings ADD CONSTRAINT macro_binding_admitted_context_fk
 FOREIGN KEY (brief_id, admitted_approval_id, admitted_exposure_digest)
 REFERENCES macro_context_admissions (brief_id, approval_id, exposure_digest)
 DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_context_admissions ADD CONSTRAINT macro_admission_inputs_object
 CHECK (jsonb_typeof(resolved_inputs) = 'object');
ALTER TABLE macro_context_admissions ADD CONSTRAINT macro_admission_pins_array
 CHECK (jsonb_typeof(pins) = 'array');
CREATE TRIGGER macro_context_admission_immutable
 BEFORE UPDATE OR DELETE ON macro_context_admissions
 FOR EACH ROW EXECUTE FUNCTION macro_agent_reject_history_change();
CREATE FUNCTION macro_agent_guard_binding_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN
  RAISE EXCEPTION 'thesis binding cannot be deleted' USING ERRCODE = '23514';
 END IF;
 IF ROW(NEW.brief_id, NEW.thesis_id, NEW.owner_id, NEW.created_at)
    IS DISTINCT FROM ROW(OLD.brief_id, OLD.thesis_id, OLD.owner_id, OLD.created_at) THEN
  RAISE EXCEPTION 'thesis binding identity is immutable' USING ERRCODE = '23514';
 END IF;
 IF OLD.observed_at IS NOT NULL AND (NEW.observed_at IS NULL OR NEW.observed_at < OLD.observed_at) THEN
  RAISE EXCEPTION 'context observation cannot move backwards' USING ERRCODE = '23514';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER macro_thesis_binding_identity_guard
 BEFORE UPDATE OR DELETE ON macro_thesis_brief_bindings
 FOR EACH ROW EXECUTE FUNCTION macro_agent_guard_binding_identity();

ALTER TABLE "macro_context_admissions" ADD CONSTRAINT "macro_context_admiss_approval_id_99e7fbec_fk_macro_the" FOREIGN KEY ("approval_id") REFERENCES "macro_thesis_approvals" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "macro_context_admissions" ADD CONSTRAINT "macro_context_admiss_brief_id_9f254207_fk_macro_bri" FOREIGN KEY ("brief_id") REFERENCES "macro_brief_states" ("brief_id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "macro_context_admissions" ADD CONSTRAINT "macro_context_admissions_thesis_id_0c6d56bb_fk_macro_theses_id" FOREIGN KEY ("thesis_id") REFERENCES "macro_theses" ("id") DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX "macro_context_admissions_approval_id_99e7fbec" ON "macro_context_admissions" ("approval_id");
CREATE INDEX "macro_context_admissions_brief_id_9f254207" ON "macro_context_admissions" ("brief_id");
CREATE INDEX "macro_context_admissions_brief_id_9f254207_like" ON "macro_context_admissions" ("brief_id" varchar_pattern_ops);
CREATE INDEX "macro_context_admissions_thesis_id_0c6d56bb" ON "macro_context_admissions" ("thesis_id");
ALTER TABLE "macro_thesis_brief_bindings" ADD CONSTRAINT "macro_thesis_brief_b_brief_id_a4702ae8_fk_macro_bri" FOREIGN KEY ("brief_id") REFERENCES "macro_brief_states" ("brief_id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "macro_thesis_brief_bindings" ADD CONSTRAINT "macro_thesis_brief_b_admitted_approval_id_6b95db1c_fk_macro_the" FOREIGN KEY ("admitted_approval_id") REFERENCES "macro_thesis_approvals" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "macro_thesis_brief_bindings" ADD CONSTRAINT "macro_thesis_brief_b_owner_id_e4fa9a36_fk_macro_web" FOREIGN KEY ("owner_id") REFERENCES "macro_web_user" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "macro_thesis_brief_bindings" ADD CONSTRAINT "macro_thesis_brief_b_thesis_id_d4ff9410_fk_macro_the" FOREIGN KEY ("thesis_id") REFERENCES "macro_theses" ("id") DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX "macro_thesis_brief_bindings_brief_id_a4702ae8_like" ON "macro_thesis_brief_bindings" ("brief_id" varchar_pattern_ops);
CREATE INDEX "macro_thesis_brief_bindings_admitted_approval_id_6b95db1c" ON "macro_thesis_brief_bindings" ("admitted_approval_id");
CREATE INDEX "macro_thesis_brief_bindings_owner_id_e4fa9a36" ON "macro_thesis_brief_bindings" ("owner_id");
CREATE INDEX "macro_thesis_brief_bindings_thesis_id_d4ff9410" ON "macro_thesis_brief_bindings" ("thesis_id");
COMMIT;
