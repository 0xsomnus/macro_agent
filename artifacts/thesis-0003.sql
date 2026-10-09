BEGIN;
--
-- Add field review_card to interpretationrecord
--
ALTER TABLE "macro_thesis_interpretations" ADD COLUMN "review_card" jsonb NULL;
--
-- Create model RefinementSubmission
--
CREATE TABLE "macro_refinement_submissions" ("id" uuid NOT NULL PRIMARY KEY, "command_id" uuid NOT NULL, "expected_revision" bigint NOT NULL CHECK ("expected_revision" >= 0), "request_digest" varchar(64) NOT NULL, "answers" jsonb NOT NULL, "cumulative_inputs" jsonb NOT NULL, "created_at" timestamp with time zone NOT NULL, "owner_id" uuid NOT NULL, "parent_attempt_id" uuid NOT NULL, "text_version_id" uuid NOT NULL, "thesis_id" uuid NOT NULL);
--
-- Add field refinement to compilationattempt
--
ALTER TABLE "macro_compilation_attempts" ADD COLUMN "refinement_id" uuid NULL CONSTRAINT "macro_compilation_at_refinement_id_6c769f4d_fk_macro_ref" REFERENCES "macro_refinement_submissions"("id") DEFERRABLE INITIALLY DEFERRED; SET CONSTRAINTS "macro_compilation_at_refinement_id_6c769f4d_fk_macro_ref" IMMEDIATE;
--
-- Create constraint macro_refine_command_identity on model refinementsubmission
--
ALTER TABLE "macro_refinement_submissions" ADD CONSTRAINT "macro_refine_command_identity" UNIQUE ("owner_id", "command_id");
--
-- Create constraint macro_refine_text_target on model refinementsubmission
--
ALTER TABLE "macro_refinement_submissions" ADD CONSTRAINT "macro_refine_text_target" UNIQUE ("thesis_id", "text_version_id", "id");
--
-- Create constraint macro_refine_revision_positive on model refinementsubmission
--
ALTER TABLE "macro_refinement_submissions" ADD CONSTRAINT "macro_refine_revision_positive" CHECK ("expected_revision" > 0);
--
-- Create constraint macro_refine_request_digest on model refinementsubmission
--
ALTER TABLE "macro_refinement_submissions" ADD CONSTRAINT "macro_refine_request_digest" CHECK ("request_digest"::text ~ '^[0-9a-f]{64}$');
--
-- Raw SQL operation
--

ALTER TABLE macro_thesis_interpretations ADD CONSTRAINT macro_interp_card_object
    CHECK (review_card IS NULL OR (origin = 'model_compilation' AND jsonb_typeof(review_card) = 'object'));
ALTER TABLE macro_refinement_submissions ADD CONSTRAINT macro_refine_owner_scope_fk
    FOREIGN KEY (thesis_id, owner_id) REFERENCES macro_theses (id, owner_id)
    DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_refinement_submissions ADD CONSTRAINT macro_refine_parent_scope_fk
    FOREIGN KEY (thesis_id, text_version_id, parent_attempt_id)
    REFERENCES macro_compilation_attempts (thesis_id, text_version_id, id)
    DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_compilation_attempts ADD CONSTRAINT macro_compile_refine_scope_fk
    FOREIGN KEY (thesis_id, text_version_id, refinement_id)
    REFERENCES macro_refinement_submissions (thesis_id, text_version_id, id)
    DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_refinement_submissions ADD CONSTRAINT macro_refine_answers_array
    CHECK (CASE WHEN jsonb_typeof(answers) = 'array'
           THEN jsonb_array_length(answers) BETWEEN 1 AND 16 ELSE FALSE END);
ALTER TABLE macro_refinement_submissions ADD CONSTRAINT macro_refine_inputs_array
    CHECK (CASE WHEN jsonb_typeof(cumulative_inputs) = 'array'
           THEN jsonb_array_length(cumulative_inputs) BETWEEN 1 AND 16 ELSE FALSE END);
CREATE TRIGGER macro_refine_immutable BEFORE UPDATE OR DELETE ON macro_refinement_submissions
    FOR EACH ROW EXECUTE FUNCTION macro_thesis_reject_history_change();

CREATE FUNCTION macro_refine_guard_parent() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent macro_compilation_attempts%ROWTYPE;
DECLARE completed macro_compilation_results%ROWTYPE;
DECLARE prior jsonb := '[]'::jsonb;
DECLARE prior_count integer;
DECLARE i integer;
BEGIN
    SELECT * INTO STRICT parent FROM macro_compilation_attempts WHERE id = NEW.parent_attempt_id;
    SELECT * INTO STRICT completed FROM macro_compilation_results WHERE attempt_id = parent.id;
    IF completed.status <> 'compiled' OR NEW.created_at < completed.finished_at
       OR NEW.expected_revision <= parent.expected_revision THEN
        RAISE EXCEPTION 'refinement requires an available completed parent' USING ERRCODE = '23514';
    END IF;
    IF parent.refinement_id IS NOT NULL THEN
        SELECT cumulative_inputs INTO STRICT prior FROM macro_refinement_submissions
            WHERE id = parent.refinement_id;
    END IF;
    prior_count := jsonb_array_length(prior);
    IF jsonb_typeof(NEW.answers) <> 'array' OR jsonb_typeof(NEW.cumulative_inputs) <> 'array'
       OR jsonb_array_length(NEW.cumulative_inputs) <> prior_count + jsonb_array_length(NEW.answers) THEN
        RAISE EXCEPTION 'refinement must retain its exact answer history' USING ERRCODE = '23514';
    END IF;
    IF prior_count > 0 THEN
        FOR i IN 0..prior_count - 1 LOOP
            IF NEW.cumulative_inputs -> i IS DISTINCT FROM prior -> i THEN
                RAISE EXCEPTION 'refinement cannot replace earlier answers' USING ERRCODE = '23514';
            END IF;
        END LOOP;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER macro_refine_parent BEFORE INSERT ON macro_refinement_submissions
    FOR EACH ROW EXECUTE FUNCTION macro_refine_guard_parent();

CREATE FUNCTION macro_compile_guard_refinement_time() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE available_at timestamptz;
BEGIN
    IF NEW.refinement_id IS NOT NULL THEN
        SELECT created_at INTO STRICT available_at FROM macro_refinement_submissions
            WHERE id = NEW.refinement_id;
        IF NEW.created_at < available_at THEN
            RAISE EXCEPTION 'compilation cannot precede saved answers' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER macro_compile_refinement_time BEFORE INSERT ON macro_compilation_attempts
    FOR EACH ROW EXECUTE FUNCTION macro_compile_guard_refinement_time();

ALTER TABLE "macro_refinement_submissions" ADD CONSTRAINT "macro_refinement_sub_owner_id_eb2b0202_fk_macro_web" FOREIGN KEY ("owner_id") REFERENCES "macro_web_user" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "macro_refinement_submissions" ADD CONSTRAINT "macro_refinement_sub_parent_attempt_id_234b315d_fk_macro_com" FOREIGN KEY ("parent_attempt_id") REFERENCES "macro_compilation_attempts" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "macro_refinement_submissions" ADD CONSTRAINT "macro_refinement_sub_text_version_id_3a9f8ec2_fk_macro_the" FOREIGN KEY ("text_version_id") REFERENCES "macro_thesis_text_versions" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "macro_refinement_submissions" ADD CONSTRAINT "macro_refinement_sub_thesis_id_1913983b_fk_macro_the" FOREIGN KEY ("thesis_id") REFERENCES "macro_theses" ("id") DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX "macro_refinement_submissions_owner_id_eb2b0202" ON "macro_refinement_submissions" ("owner_id");
CREATE INDEX "macro_refinement_submissions_parent_attempt_id_234b315d" ON "macro_refinement_submissions" ("parent_attempt_id");
CREATE INDEX "macro_refinement_submissions_text_version_id_3a9f8ec2" ON "macro_refinement_submissions" ("text_version_id");
CREATE INDEX "macro_refinement_submissions_thesis_id_1913983b" ON "macro_refinement_submissions" ("thesis_id");
CREATE INDEX "macro_compilation_attempts_refinement_id_6c769f4d" ON "macro_compilation_attempts" ("refinement_id");
COMMIT;
