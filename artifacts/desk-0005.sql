BEGIN;
--
-- Create model DailyBrief
--
CREATE TABLE "macro_desk_dailybrief" ("brief_id" varchar(255) NOT NULL PRIMARY KEY, "fanout_limit" integer NOT NULL CHECK ("fanout_limit" >= 0), "created_at" timestamp with time zone NOT NULL, "owner_id" uuid NOT NULL, "thesis_id" uuid NOT NULL UNIQUE, CONSTRAINT "desk_daily_binding_scope" UNIQUE ("brief_id", "owner_id", "thesis_id"), CONSTRAINT "desk_daily_fanout_explicit" CHECK (("fanout_limit" >= 1 AND "fanout_limit" <= 1000)));
--
-- Create model DailyPublication
--
CREATE TABLE "macro_desk_dailypublication" ("id" uuid NOT NULL PRIMARY KEY, "command_id" uuid NOT NULL, "request_digest" varchar(64) NOT NULL, "expected_generation" bigint NOT NULL CHECK ("expected_generation" >= 0), "published_at" timestamp with time zone NOT NULL, "assessment_id" bigint NOT NULL UNIQUE, "brief_id" varchar(255) NOT NULL, "owner_id" uuid NOT NULL, "review_id" uuid NOT NULL UNIQUE, "thesis_id" uuid NOT NULL, CONSTRAINT "desk_daily_publication_command" UNIQUE ("owner_id", "command_id"), CONSTRAINT "desk_daily_request_digest" CHECK ("request_digest"::text ~ '^[0-9a-f]{64}$'));
--
-- Raw SQL operation
--

ALTER TABLE macro_desk_dailybrief ADD CONSTRAINT desk_daily_brief_owner_fk
 FOREIGN KEY (brief_id,owner_id) REFERENCES macro_brief_states(brief_id,owner_id)
 DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_desk_dailybrief ADD CONSTRAINT desk_daily_thesis_owner_fk
 FOREIGN KEY (thesis_id,owner_id) REFERENCES macro_theses(id,owner_id)
 DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_desk_dailypublication ADD CONSTRAINT desk_daily_publication_binding_fk
 FOREIGN KEY (brief_id,owner_id,thesis_id) REFERENCES macro_desk_dailybrief(brief_id,owner_id,thesis_id)
 DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE macro_desk_dailypublication ADD CONSTRAINT desk_daily_publication_assessment_fk
 FOREIGN KEY (brief_id,assessment_id) REFERENCES macro_assessments(brief_id,id)
 DEFERRABLE INITIALLY IMMEDIATE;

CREATE FUNCTION desk_daily_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='macro_desk_dailybrief' THEN
  IF EXISTS (SELECT 1 FROM macro_thesis_brief_bindings WHERE brief_id=NEW.brief_id)
   OR EXISTS (SELECT 1 FROM macro_dependency_heads WHERE brief_id=NEW.brief_id)
   OR EXISTS (SELECT 1 FROM macro_assessments WHERE brief_id=NEW.brief_id)
   OR NOT EXISTS (SELECT 1 FROM macro_brief_states WHERE brief_id=NEW.brief_id
    AND owner_id=NEW.owner_id AND generation=0 AND changed_at=NEW.created_at) THEN
   RAISE EXCEPTION 'daily binding requires a new private daily stream' USING ERRCODE='23514';
  END IF;
 ELSIF EXISTS (SELECT 1 FROM macro_desk_dailybrief WHERE brief_id=NEW.brief_id) THEN
  RAISE EXCEPTION 'daily stream cannot acquire factual-notice bindings or heads' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER desk_daily_binding_scope BEFORE INSERT ON macro_desk_dailybrief
 FOR EACH ROW EXECUTE FUNCTION desk_daily_binding_guard();
CREATE TRIGGER desk_daily_binding_exclusive BEFORE INSERT ON macro_thesis_brief_bindings
 FOR EACH ROW EXECUTE FUNCTION desk_daily_binding_guard();
CREATE TRIGGER desk_daily_heads_exclusive BEFORE INSERT ON macro_dependency_heads
 FOR EACH ROW EXECUTE FUNCTION desk_daily_binding_guard();
CREATE TRIGGER desk_daily_binding_immutable BEFORE UPDATE OR DELETE ON macro_desk_dailybrief
 FOR EACH ROW EXECUTE FUNCTION desk_reject_change();
CREATE TRIGGER desk_daily_publication_immutable BEFORE UPDATE OR DELETE ON macro_desk_dailypublication
 FOR EACH ROW EXECUTE FUNCTION desk_reject_change();

CREATE FUNCTION desk_daily_context_current(context_id uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
 SELECT EXISTS (SELECT 1 FROM macro_desk_privatecontext c
  JOIN macro_theses t ON t.id=c.thesis_id
  WHERE c.id=context_id AND t.current_approval_id=c.approval_id
  AND NOT EXISTS (SELECT 1 FROM macro_paper_positions p WHERE p.thesis_id=c.thesis_id
   AND (p.current_version_id IS NULL OR NOT EXISTS
    (SELECT 1 FROM macro_desk_contextexposure x WHERE x.context_id=c.id
     AND x.position_id=p.id AND x.version_id=p.current_version_id)))
  AND NOT EXISTS (SELECT 1 FROM macro_desk_contextexposure x
   JOIN macro_paper_positions p ON p.id=x.position_id
   WHERE x.context_id=c.id AND p.current_version_id IS DISTINCT FROM x.version_id)
  AND NOT EXISTS (SELECT 1 FROM macro_desk_evidencesource es
   JOIN macro_desk_sourcecontractversion v ON v.id=es.contract_id
   JOIN macro_monitoring_sourcestate s ON s.id=es.source_id
   LEFT JOIN macro_desk_sourcecontracthead h ON h.source_id=es.source_id
   WHERE es.evidence_id=c.evidence_id AND (h.version_id IS DISTINCT FROM es.contract_id
    OR NOT v.permitted OR s.contract_digest<>v.digest OR s.contract IS DISTINCT FROM v.contract))
  AND NOT EXISTS (SELECT 1 FROM macro_desk_evidencerevision er
   JOIN macro_monitoring_sourcerevision v ON v.id=er.revision_id
   JOIN macro_monitoring_sourcereport r ON r.id=v.report_id
   WHERE er.evidence_id=c.evidence_id AND r.current_revision_id IS DISTINCT FROM er.head_at_preparation_id));
$$;

CREATE FUNCTION desk_daily_publication_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r macro_desk_dailyreview%ROWTYPE; c macro_desk_privatecontext%ROWTYPE;
 a macro_assessments%ROWTYPE; b macro_brief_states%ROWTYPE; payload jsonb;
BEGIN
 SELECT * INTO r FROM macro_desk_dailyreview WHERE id=NEW.review_id;
 SELECT * INTO c FROM macro_desk_privatecontext WHERE id=r.context_id;
 SELECT * INTO a FROM macro_assessments WHERE id=NEW.assessment_id;
 SELECT * INTO b FROM macro_brief_states WHERE brief_id=NEW.brief_id;
 payload := a.payload::jsonb;
 IF r.id IS NULL OR r.owner_id IS DISTINCT FROM NEW.owner_id OR r.thesis_id IS DISTINCT FROM NEW.thesis_id
  OR c.owner_id IS DISTINCT FROM NEW.owner_id OR c.thesis_id IS DISTINCT FROM NEW.thesis_id
  OR a.brief_id IS DISTINCT FROM NEW.brief_id OR a.saved_at IS DISTINCT FROM NEW.published_at
  OR NEW.published_at<r.prepared_at OR NEW.published_at<b.changed_at
  OR NEW.expected_generation>b.generation
  OR a.assessment_id IS DISTINCT FROM 'daily:'||r.id::text
  OR a.digest IS DISTINCT FROM encode(sha256(convert_to(a.payload,'UTF8')),'hex')
  OR payload->>'kind' IS DISTINCT FROM 'daily_evidence_review'
  OR payload->>'command_id' IS DISTINCT FROM NEW.command_id::text
  OR payload->>'assessment_id' IS DISTINCT FROM a.assessment_id
  OR payload->>'owner_id' IS DISTINCT FROM NEW.owner_id::text
  OR payload->>'thesis_id' IS DISTINCT FROM NEW.thesis_id::text
  OR payload->>'brief_id' IS DISTINCT FROM NEW.brief_id
  OR payload->>'review_id' IS DISTINCT FROM r.id::text
  OR payload->>'context_id' IS DISTINCT FROM c.id::text
  OR payload->>'review_digest' IS DISTINCT FROM r.digest
  OR (payload->>'cutoff')::timestamptz IS DISTINCT FROM r.cutoff
  OR payload->>'approval_id' IS DISTINCT FROM c.approval_id::text
  OR payload->>'exposure_digest' IS DISTINCT FROM c.exposure_digest
  OR payload->'expected_generation' IS DISTINCT FROM to_jsonb(NEW.expected_generation)
  OR payload->'content' IS DISTINCT FROM r.content THEN
  RAISE EXCEPTION 'daily publication does not bind exact scoped review and assessment' USING ERRCODE='23514';
 END IF;
 IF a.status='current' AND (NOT desk_daily_context_current(c.id)
  OR NEW.expected_generation<>b.generation OR a.reassessment_required
  OR a.reasons IS DISTINCT FROM '["all_dependencies_current"]'::jsonb
  OR EXISTS (SELECT 1 FROM macro_desk_dailyreview later WHERE later.thesis_id=r.thesis_id AND later.cutoff>r.cutoff)
  OR EXISTS (SELECT 1 FROM macro_desk_dailypublication earlier
   JOIN macro_assessments ea ON ea.id=earlier.assessment_id
   JOIN macro_desk_dailyreview er ON er.id=earlier.review_id
   WHERE earlier.brief_id=NEW.brief_id AND ea.status='current' AND er.cutoff>=r.cutoff)) THEN
  RAISE EXCEPTION 'daily publication cannot reactivate stale or older evidence' USING ERRCODE='23514';
 END IF;
 IF a.status='superseded' AND jsonb_array_length(a.reasons)=0 THEN
  RAISE EXCEPTION 'superseded daily publication requires original reasons' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER desk_daily_publication_scope BEFORE INSERT ON macro_desk_dailypublication
 FOR EACH ROW EXECUTE FUNCTION desk_daily_publication_guard();

CREATE FUNCTION desk_daily_pointer_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE publication macro_desk_dailypublication%ROWTYPE; a macro_assessments%ROWTYPE;
 r macro_desk_dailyreview%ROWTYPE; b macro_brief_states%ROWTYPE;
BEGIN
 IF NOT EXISTS (SELECT 1 FROM macro_desk_dailybrief WHERE brief_id=NEW.brief_id) THEN
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='macro_notification_intents' THEN
  IF NEW.state='delivered' THEN
   RAISE EXCEPTION 'daily notification has no delivery authority' USING ERRCODE='23514';
  END IF;
  IF NEW.state<>'pending' THEN RETURN NEW; END IF;
 END IF;
 SELECT * INTO publication FROM macro_desk_dailypublication WHERE assessment_id=NEW.assessment_id;
 SELECT * INTO a FROM macro_assessments WHERE id=NEW.assessment_id;
 SELECT * INTO r FROM macro_desk_dailyreview WHERE id=publication.review_id;
 SELECT * INTO b FROM macro_brief_states WHERE brief_id=NEW.brief_id;
 IF publication.id IS NULL OR publication.brief_id IS DISTINCT FROM NEW.brief_id
  OR a.status IS DISTINCT FROM 'current' OR NOT desk_daily_context_current(r.context_id)
  OR b.generation IS DISTINCT FROM publication.expected_generation+1
  OR EXISTS (SELECT 1 FROM macro_desk_dailyreview later WHERE later.thesis_id=r.thesis_id AND later.cutoff>r.cutoff)
  OR EXISTS (SELECT 1 FROM macro_desk_dailypublication later
   JOIN macro_assessments la ON la.id=later.assessment_id
   JOIN macro_desk_dailyreview lr ON lr.id=later.review_id
   WHERE later.brief_id=NEW.brief_id AND la.status='current' AND lr.cutoff>r.cutoff) THEN
  RAISE EXCEPTION 'daily current state requires the latest exact permitted publication' USING ERRCODE='23514';
 END IF;
 IF TG_TABLE_NAME='macro_current_assessments' THEN
  IF EXISTS (SELECT 1 FROM macro_brief_versions v WHERE v.assessment_id=NEW.assessment_id)
   AND (TG_OP='INSERT' OR NEW.assessment_id IS DISTINCT FROM OLD.assessment_id) THEN
   RAISE EXCEPTION 'historical daily publication cannot reinstall current state' USING ERRCODE='23514';
  END IF;
 END IF;
 IF TG_TABLE_NAME='macro_brief_versions' THEN
  IF NEW.generation<>b.generation OR NEW.saved_at IS DISTINCT FROM publication.published_at
   OR NOT EXISTS (SELECT 1 FROM macro_current_assessments WHERE brief_id=NEW.brief_id AND assessment_id=NEW.assessment_id) THEN
   RAISE EXCEPTION 'daily version must match protected current generation' USING ERRCODE='23514';
  END IF;
 ELSIF TG_TABLE_NAME='macro_notification_intents' THEN
  IF NEW.created_at IS DISTINCT FROM publication.published_at
   OR NEW.intent_id IS DISTINCT FROM 'notice:'||encode(sha256(convert_to(format('[%s,%s,%s]',
    to_json(publication.owner_id::text)::text,to_json(NEW.brief_id)::text,to_json(a.assessment_id)::text),'UTF8')),'hex')
   OR NOT EXISTS (SELECT 1 FROM macro_current_assessments WHERE brief_id=NEW.brief_id AND assessment_id=NEW.assessment_id)
   OR EXISTS (SELECT 1 FROM macro_notification_intents i WHERE i.brief_id=NEW.brief_id AND i.state='pending' AND i.intent_id<>NEW.intent_id) THEN
   RAISE EXCEPTION 'daily pending intent requires its sole exact current publication' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER desk_daily_current_scope BEFORE INSERT OR UPDATE ON macro_current_assessments
 FOR EACH ROW EXECUTE FUNCTION desk_daily_pointer_guard();
CREATE TRIGGER desk_daily_version_scope BEFORE INSERT ON macro_brief_versions
 FOR EACH ROW EXECUTE FUNCTION desk_daily_pointer_guard();
CREATE TRIGGER desk_daily_notice_scope BEFORE INSERT OR UPDATE ON macro_notification_intents
 FOR EACH ROW EXECUTE FUNCTION desk_daily_pointer_guard();

CREATE FUNCTION desk_daily_pending_pointer_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE brief varchar;
BEGIN
 IF TG_OP='DELETE' THEN brief:=OLD.brief_id; ELSE brief:=NEW.brief_id; END IF;
 IF EXISTS (SELECT 1 FROM macro_desk_dailybrief WHERE brief_id=brief)
  AND EXISTS (SELECT 1 FROM macro_notification_intents i WHERE i.brief_id=brief AND i.state='pending'
   AND NOT EXISTS (SELECT 1 FROM macro_current_assessments h
    WHERE h.brief_id=i.brief_id AND h.assessment_id=i.assessment_id)) THEN
  RAISE EXCEPTION 'daily pending notice must retain its exact current pointer' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER desk_daily_pending_pointer AFTER INSERT OR UPDATE OR DELETE ON macro_current_assessments
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION desk_daily_pending_pointer_guard();

CREATE FUNCTION desk_daily_governing_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE thesis uuid;
BEGIN
 IF TG_TABLE_NAME='macro_theses' THEN thesis:=NEW.id; ELSE thesis:=NEW.thesis_id; END IF;
 IF EXISTS (SELECT 1 FROM macro_desk_dailypublication p
  JOIN macro_desk_dailyreview r ON r.id=p.review_id WHERE p.thesis_id=thesis
  AND (EXISTS (SELECT 1 FROM macro_current_assessments h WHERE h.assessment_id=p.assessment_id)
   OR EXISTS (SELECT 1 FROM macro_notification_intents i WHERE i.assessment_id=p.assessment_id AND i.state='pending'))
  AND NOT desk_daily_context_current(r.context_id)) THEN
  RAISE EXCEPTION 'governing change must invalidate daily current state and pending notices atomically' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER desk_daily_approval_changed AFTER UPDATE ON macro_theses
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION desk_daily_governing_guard();
CREATE FUNCTION desk_daily_position_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM 1 FROM macro_theses WHERE id=NEW.thesis_id FOR UPDATE;
 RETURN NEW;
END $$;
CREATE TRIGGER desk_daily_exposure_lock BEFORE INSERT OR UPDATE ON macro_paper_positions
 FOR EACH ROW EXECUTE FUNCTION desk_daily_position_lock();
CREATE CONSTRAINT TRIGGER desk_daily_exposure_changed AFTER INSERT OR UPDATE ON macro_paper_positions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION desk_daily_governing_guard();

CREATE FUNCTION desk_daily_source_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source varchar; report bigint;
BEGIN
 IF TG_TABLE_NAME='macro_monitoring_sourcereport' THEN
  IF NEW.current_revision_id IS NOT DISTINCT FROM OLD.current_revision_id THEN RETURN NEW; END IF;
  source:=NEW.source_id; report:=NEW.id;
 ELSE
  source:=NEW.source_id; report:=NULL;
 END IF;
 PERFORM 1 FROM macro_monitoring_sourcestate WHERE id=source FOR UPDATE;
 IF EXISTS (SELECT 1 FROM macro_desk_dailypublication p
  JOIN macro_desk_dailyreview r ON r.id=p.review_id
  JOIN macro_desk_privatecontext c ON c.id=r.context_id
  WHERE (EXISTS (SELECT 1 FROM macro_current_assessments h WHERE h.assessment_id=p.assessment_id)
   OR EXISTS (SELECT 1 FROM macro_notification_intents i WHERE i.assessment_id=p.assessment_id AND i.state='pending'))
  AND ((report IS NULL AND EXISTS (SELECT 1 FROM macro_desk_evidencesource es
    WHERE es.evidence_id=c.evidence_id AND es.source_id=source))
   OR (report IS NOT NULL AND EXISTS (SELECT 1 FROM macro_desk_evidencerevision er
    JOIN macro_monitoring_sourcerevision v ON v.id=er.revision_id
    WHERE er.evidence_id=c.evidence_id AND v.report_id=report)))) THEN
  RAISE EXCEPTION 'source correction or permission must first invalidate dependent daily output' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER desk_daily_report_changed BEFORE UPDATE OF current_revision_id ON macro_monitoring_sourcereport
 FOR EACH ROW EXECUTE FUNCTION desk_daily_source_guard();
CREATE TRIGGER desk_daily_permission_changed BEFORE INSERT OR UPDATE ON macro_desk_sourcecontracthead
 FOR EACH ROW EXECUTE FUNCTION desk_daily_source_guard();

ALTER TABLE "macro_desk_dailybrief" ADD CONSTRAINT "macro_desk_dailybrie_brief_id_f9370681_fk_macro_bri" FOREIGN KEY ("brief_id") REFERENCES "macro_brief_states" ("brief_id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "macro_desk_dailybrief" ADD CONSTRAINT "macro_desk_dailybrief_owner_id_5117d0cb_fk_macro_web_user_id" FOREIGN KEY ("owner_id") REFERENCES "macro_web_user" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "macro_desk_dailybrief" ADD CONSTRAINT "macro_desk_dailybrief_thesis_id_0b7e6e09_fk_macro_theses_id" FOREIGN KEY ("thesis_id") REFERENCES "macro_theses" ("id") DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX "macro_desk_dailybrief_brief_id_f9370681_like" ON "macro_desk_dailybrief" ("brief_id" varchar_pattern_ops);
CREATE INDEX "macro_desk_dailybrief_owner_id_5117d0cb" ON "macro_desk_dailybrief" ("owner_id");
ALTER TABLE "macro_desk_dailypublication" ADD CONSTRAINT "macro_desk_dailypubl_assessment_id_2a6bbcbe_fk_macro_ass" FOREIGN KEY ("assessment_id") REFERENCES "macro_assessments" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "macro_desk_dailypublication" ADD CONSTRAINT "macro_desk_dailypubl_brief_id_ba44271b_fk_macro_bri" FOREIGN KEY ("brief_id") REFERENCES "macro_brief_states" ("brief_id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "macro_desk_dailypublication" ADD CONSTRAINT "macro_desk_dailypubl_owner_id_2e432f44_fk_macro_web" FOREIGN KEY ("owner_id") REFERENCES "macro_web_user" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "macro_desk_dailypublication" ADD CONSTRAINT "macro_desk_dailypubl_review_id_e06e72c1_fk_macro_des" FOREIGN KEY ("review_id") REFERENCES "macro_desk_dailyreview" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "macro_desk_dailypublication" ADD CONSTRAINT "macro_desk_dailypubl_thesis_id_1557394d_fk_macro_the" FOREIGN KEY ("thesis_id") REFERENCES "macro_theses" ("id") DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX "macro_desk_dailypublication_brief_id_ba44271b" ON "macro_desk_dailypublication" ("brief_id");
CREATE INDEX "macro_desk_dailypublication_brief_id_ba44271b_like" ON "macro_desk_dailypublication" ("brief_id" varchar_pattern_ops);
CREATE INDEX "macro_desk_dailypublication_owner_id_2e432f44" ON "macro_desk_dailypublication" ("owner_id");
CREATE INDEX "macro_desk_dailypublication_thesis_id_1557394d" ON "macro_desk_dailypublication" ("thesis_id");
COMMIT;
