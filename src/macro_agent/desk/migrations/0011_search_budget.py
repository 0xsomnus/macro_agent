"""Internal ledger only. No prices, credentials or paid providers are seeded."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


SQL = r"""
CREATE FUNCTION desk_search_budget_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
 price macro_desk_searchpricecontract%ROWTYPE;
 run macro_desk_researchrun%ROWTYPE;
 thesis macro_theses%ROWTYPE;
 reservation macro_desk_searchreservation%ROWTYPE;
 total bigint;
BEGIN
 IF TG_OP<>'INSERT' THEN
  RAISE EXCEPTION 'search accounting identities and outcomes are immutable' USING ERRCODE='23514';
 END IF;
 IF TG_TABLE_NAME='macro_desk_searchbudgetroot' THEN RETURN NEW; END IF;
 PERFORM 1 FROM macro_desk_searchbudgetroot WHERE id=1 FOR UPDATE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'search accounting requires its shared budget root' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='macro_desk_searchpricecontract' THEN
  PERFORM 1 FROM macro_web_user WHERE id=NEW.reviewed_by_id AND is_active AND is_staff FOR UPDATE;
  IF NOT FOUND OR jsonb_typeof(NEW.document) IS DISTINCT FROM 'object'
   OR NOT (NEW.document ?& ARRAY['schema_version','provider_id','currency','billing_basis',
       'maximum_charge_microusd','pricing_reference','pricing_evidence_digest'])
   OR (SELECT count(*) FROM jsonb_object_keys(NEW.document))<>7
   OR NEW.document->>'schema_version' IS DISTINCT FROM 'search-request-price-v1'
   OR NEW.document->>'provider_id' IS DISTINCT FROM NEW.provider_id
   OR NEW.provider_id !~ '^[a-z][a-z0-9_-]{0,31}$'
   OR NEW.document->>'currency' IS DISTINCT FROM 'USD'
   OR NEW.document->>'billing_basis' IS DISTINCT FROM 'per_request_upper_bound'
   OR jsonb_typeof(NEW.document->'maximum_charge_microusd') IS DISTINCT FROM 'number'
   OR NEW.document->'maximum_charge_microusd' IS DISTINCT FROM to_jsonb(NEW.maximum_charge_microusd)
   OR NOT coalesce(NEW.document->>'maximum_charge_microusd' ~ '^[1-9][0-9]*$',false)
   OR jsonb_typeof(NEW.document->'pricing_reference') IS DISTINCT FROM 'string'
   OR NOT coalesce(length(btrim(NEW.document->>'pricing_reference')) BETWEEN 1 AND 512,false)
   OR NOT coalesce(NEW.document->>'pricing_evidence_digest' ~ '^[0-9a-f]{64}$',false) THEN
   RAISE EXCEPTION 'search price requires an exact bounded named-staff review' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
 END IF;
 IF TG_TABLE_NAME='macro_desk_searchreservation' THEN
  PERFORM 1 FROM macro_web_user WHERE id=NEW.owner_id AND is_active FOR UPDATE;
  IF NOT FOUND THEN
   RAISE EXCEPTION 'search reservation requires an active owner' USING ERRCODE='23514'; END IF;
  SELECT * INTO run FROM macro_desk_researchrun WHERE id=NEW.run_id;
  SELECT * INTO thesis FROM macro_theses WHERE id=run.thesis_id FOR UPDATE;
  SELECT * INTO price FROM macro_desk_searchpricecontract WHERE digest=NEW.price_contract_id;
  IF run.id IS NULL OR run.owner_id IS DISTINCT FROM NEW.owner_id OR thesis.id IS NULL
   OR thesis.owner_id IS DISTINCT FROM NEW.owner_id OR price.digest IS NULL
   OR NEW.maximum_charge_microusd IS DISTINCT FROM price.maximum_charge_microusd
   OR NEW.created_at<run.created_at OR NEW.created_at<price.reviewed_at
   OR NEW.created_at<thesis.changed_at
   OR NEW.month_start IS DISTINCT FROM date_trunc('month',NEW.created_at AT TIME ZONE 'UTC')::date
   OR thesis.revision IS DISTINCT FROM run.initial_revision
   OR thesis.latest_text_id IS DISTINCT FROM run.initial_text_id OR thesis.current_approval_id IS NOT NULL THEN
   RAISE EXCEPTION 'search reservation requires exact owned current research and price' USING ERRCODE='23514';
  END IF;
  SELECT coalesce(sum(coalesce(s.actual_charge_microusd,r.maximum_charge_microusd)),0) INTO total
   FROM macro_desk_searchreservation r LEFT JOIN macro_desk_searchsettlement s ON s.reservation_id=r.id
   WHERE r.month_start=NEW.month_start;
  IF total+NEW.maximum_charge_microusd>10000000 THEN
   RAISE EXCEPTION 'shared UTC-month search budget exhausted' USING ERRCODE='23514'; END IF;
  SELECT coalesce(sum(coalesce(s.actual_charge_microusd,r.maximum_charge_microusd)),0) INTO total
   FROM macro_desk_searchreservation r LEFT JOIN macro_desk_searchsettlement s ON s.reservation_id=r.id
   WHERE r.run_id=NEW.run_id;
  IF total+NEW.maximum_charge_microusd>100000 THEN
   RAISE EXCEPTION 'investigation lifetime search budget exhausted' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO reservation FROM macro_desk_searchreservation WHERE id=NEW.reservation_id;
 PERFORM 1 FROM macro_web_user WHERE id IN (NEW.operator_id,reservation.owner_id) ORDER BY id FOR UPDATE;
 IF reservation.id IS NULL OR NOT EXISTS (
     SELECT 1 FROM macro_web_user WHERE id=NEW.operator_id AND is_active AND is_staff)
  OR NEW.actual_charge_microusd>reservation.maximum_charge_microusd
  OR NEW.recorded_at<reservation.created_at
  OR jsonb_typeof(NEW.provenance) IS DISTINCT FROM 'object'
  OR NOT (NEW.provenance ?& ARRAY['kind','reference','evidence_digest'])
  OR (SELECT count(*) FROM jsonb_object_keys(NEW.provenance))<>3
  OR NEW.provenance->>'kind' IS DISTINCT FROM (CASE WHEN NEW.actual_charge_microusd=0
     THEN 'provider_zero_charge_confirmation' ELSE 'provider_charge_record' END)
  OR jsonb_typeof(NEW.provenance->'reference') IS DISTINCT FROM 'string'
  OR NOT coalesce(length(btrim(NEW.provenance->>'reference')) BETWEEN 1 AND 512,false)
  OR NOT coalesce(NEW.provenance->>'evidence_digest' ~ '^[0-9a-f]{64}$',false) THEN
  RAISE EXCEPTION 'search settlement requires bounded known charge and named operator evidence' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['macro_desk_searchbudgetroot','macro_desk_searchpricecontract',
    'macro_desk_searchreservation','macro_desk_searchsettlement'] LOOP
  EXECUTE format('CREATE TRIGGER desk_search_accounting BEFORE INSERT OR UPDATE OR DELETE ON %I '
     'FOR EACH ROW EXECUTE FUNCTION desk_search_budget_guard()',tab);
 END LOOP;
END $$;
INSERT INTO macro_desk_searchbudgetroot (id) VALUES (1);
"""
REVERSE = r"""
DO $$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['macro_desk_searchbudgetroot','macro_desk_searchpricecontract',
    'macro_desk_searchreservation','macro_desk_searchsettlement'] LOOP
  EXECUTE format('DROP TRIGGER IF EXISTS desk_search_accounting ON %I',tab);
 END LOOP;
END $$;
DROP FUNCTION IF EXISTS desk_search_budget_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("macro_desk", "0010_research_source_recovery"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(name="SearchBudgetRoot", fields=[
            ("id", models.PositiveSmallIntegerField(default=1, primary_key=True, serialize=False)),
        ], options={"constraints": [models.CheckConstraint(condition=models.Q(id=1),
            name="desk_search_budget_singleton")]}),
        migrations.CreateModel(name="SearchPriceContract", fields=[
            ("digest", models.CharField(max_length=64, primary_key=True, serialize=False)),
            ("provider_id", models.CharField(max_length=32)),
            ("maximum_charge_microusd", models.PositiveIntegerField()),
            ("document", models.JSONField()),
            ("reviewed_at", models.DateTimeField()),
            ("reviewed_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                to=settings.AUTH_USER_MODEL)),
        ], options={"constraints": [
            models.CheckConstraint(condition=models.Q(digest__regex=r"^[0-9a-f]{64}$"),
                name="desk_search_price_digest"),
            models.CheckConstraint(condition=models.Q(maximum_charge_microusd__gte=1,
                maximum_charge_microusd__lte=100_000), name="desk_search_price_bound"),
        ]}),
        migrations.CreateModel(name="SearchReservation", fields=[
            ("id", models.UUIDField(editable=False, primary_key=True, serialize=False)),
            ("maximum_charge_microusd", models.PositiveIntegerField()),
            ("month_start", models.DateField()),
            ("created_at", models.DateTimeField()),
            ("owner", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                to=settings.AUTH_USER_MODEL)),
            ("run", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                related_name="search_reservations", to="macro_desk.researchrun")),
            ("price_contract", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                to="macro_desk.searchpricecontract")),
        ], options={"constraints": [models.CheckConstraint(condition=models.Q(
            maximum_charge_microusd__gte=1, maximum_charge_microusd__lte=100_000),
            name="desk_search_reservation_bound")]}),
        migrations.CreateModel(name="SearchSettlement", fields=[
            ("reservation", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                primary_key=True, related_name="settlement", serialize=False,
                to="macro_desk.searchreservation")),
            ("actual_charge_microusd", models.PositiveIntegerField()),
            ("provenance", models.JSONField()),
            ("recorded_at", models.DateTimeField()),
            ("operator", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                to=settings.AUTH_USER_MODEL)),
        ], options={"constraints": [models.CheckConstraint(condition=models.Q(
            actual_charge_microusd__lte=100_000), name="desk_search_settlement_bound")]}),
        migrations.RunSQL(SQL, REVERSE),
    ]
