"""Initial publication records and PostgreSQL integrity safeguards.

Composite links keep every head and assessment pointer in its own brief scope.
History is append-only through ordinary writes, including queryset updates.
The application must still acquire the brief row lock before its first reads.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


ROLES = [
    "activation", "budget", "compiled_thesis", "coverage", "entitlements",
    "event_revision", "execution_graph", "exposure", "knowledge", "macro_context",
    "model", "prompt", "rules", "source_contract", "source_manifest", "user_thesis",
]
ROLE_CHOICES = [(role, role) for role in ROLES]
IMMUTABLE_TABLES = (
    "macro_dependency_versions", "macro_assessments", "macro_brief_versions",
    "macro_audit_transitions",
)
SCOPED_CONSTRAINTS = (
    ("macro_dependency_heads", "macro_head_scoped_version_fk",
     "(brief_id, role, version_id)", "macro_dependency_versions", "(brief_id, role, id)"),
    ("macro_current_assessments", "macro_current_scoped_assessment_fk",
     "(brief_id, assessment_id)", "macro_assessments", "(brief_id, id)"),
    ("macro_brief_versions", "macro_version_scoped_assessment_fk",
     "(brief_id, assessment_id)", "macro_assessments", "(brief_id, id)"),
    ("macro_notification_intents", "macro_notice_scoped_assessment_fk",
     "(brief_id, assessment_id)", "macro_assessments", "(brief_id, id)"),
)

GUARDS_SQL = """
CREATE FUNCTION macro_agent_reject_history_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'immutable history: %', TG_TABLE_NAME USING ERRCODE = '23514';
END;
$$;
CREATE FUNCTION macro_agent_protect_brief_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.brief_id IS DISTINCT FROM OLD.brief_id
       OR NEW.owner_id IS DISTINCT FROM OLD.owner_id THEN
        RAISE EXCEPTION 'brief identity and owner are immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER macro_brief_identity_guard BEFORE UPDATE ON macro_brief_states
FOR EACH ROW EXECUTE FUNCTION macro_agent_protect_brief_identity();
ALTER TABLE macro_assessments ADD CONSTRAINT macro_assessment_payload_object
    CHECK (jsonb_typeof(payload::jsonb) = 'object');
ALTER TABLE macro_assessments ADD CONSTRAINT macro_assessment_reasons_array
    CHECK (jsonb_typeof(reasons) = 'array');
ALTER TABLE macro_assessments ADD CONSTRAINT macro_assessment_observed_array
    CHECK (jsonb_typeof(observed_dependencies) = 'array');
ALTER TABLE macro_audit_transitions ADD CONSTRAINT macro_audit_detail_object
    CHECK (jsonb_typeof(detail) = 'object');
"""
for table in IMMUTABLE_TABLES:
    GUARDS_SQL += f"""
CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}
FOR EACH ROW EXECUTE FUNCTION macro_agent_reject_history_change();
"""
for table, name, columns, target, target_columns in SCOPED_CONSTRAINTS:
    GUARDS_SQL += f"""
ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY {columns}
REFERENCES {target} {target_columns} DEFERRABLE INITIALLY IMMEDIATE;
"""

REVERSE_GUARDS_SQL = ""
for table, name, _, _, _ in reversed(SCOPED_CONSTRAINTS):
    REVERSE_GUARDS_SQL += f"ALTER TABLE {table} DROP CONSTRAINT {name};\n"
for table in reversed(IMMUTABLE_TABLES):
    REVERSE_GUARDS_SQL += f"DROP TRIGGER {table}_immutable ON {table};\n"
REVERSE_GUARDS_SQL += """
ALTER TABLE macro_audit_transitions DROP CONSTRAINT macro_audit_detail_object;
ALTER TABLE macro_assessments DROP CONSTRAINT macro_assessment_observed_array;
ALTER TABLE macro_assessments DROP CONSTRAINT macro_assessment_reasons_array;
ALTER TABLE macro_assessments DROP CONSTRAINT macro_assessment_payload_object;
DROP TRIGGER macro_brief_identity_guard ON macro_brief_states;
DROP FUNCTION macro_agent_protect_brief_identity();
DROP FUNCTION macro_agent_reject_history_change();
"""


def auto_id():
    return ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                       serialize=False, verbose_name="ID"))


def brief_field(*, related_name, primary_key=False):
    field_type = models.OneToOneField if primary_key else models.ForeignKey
    return field_type(on_delete=django.db.models.deletion.PROTECT,
                      related_name=related_name, to="macro_persistence.briefstaterecord",
                      **({"primary_key": True, "serialize": False} if primary_key else {}))


def assessment_field(related_name):
    return models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                             related_name=related_name, to="macro_persistence.assessmentrecord")


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="BriefStateRecord",
            fields=[
                ("brief_id", models.CharField(max_length=255, primary_key=True, serialize=False)),
                ("generation", models.PositiveBigIntegerField(default=0)),
                ("changed_at", models.DateTimeField()),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                            related_name="macro_briefs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "macro_brief_states", "constraints": [
                models.CheckConstraint(condition=models.Q(brief_id__regex=r"\S"), name="macro_brief_id_named"),
                models.CheckConstraint(condition=models.Q(generation__gte=0), name="macro_brief_generation_nonnegative"),
            ]},
        ),
        migrations.CreateModel(
            name="DependencyVersion",
            fields=[
                auto_id(),
                ("role", models.CharField(choices=ROLE_CHOICES, max_length=64)),
                ("version_id", models.CharField(max_length=512)),
                ("digest", models.CharField(max_length=64)),
                ("known_at", models.DateTimeField()),
                ("brief", brief_field(related_name="dependency_versions")),
            ],
            options={"db_table": "macro_dependency_versions", "constraints": [
                models.UniqueConstraint(fields=("brief", "role", "version_id"), name="macro_dependency_version_identity"),
                models.UniqueConstraint(fields=("brief", "role", "id"), name="macro_dependency_scoped_target"),
                models.CheckConstraint(condition=models.Q(role__in=ROLES), name="macro_dependency_role_allowed"),
                models.CheckConstraint(condition=models.Q(version_id__regex=r"\S"), name="macro_dependency_version_named"),
                models.CheckConstraint(condition=models.Q(digest__regex=r"^[0-9a-f]{64}$"), name="macro_dependency_digest_sha256"),
            ]},
        ),
        migrations.CreateModel(
            name="DependencyHead",
            fields=[
                auto_id(),
                ("role", models.CharField(choices=ROLE_CHOICES, max_length=64)),
                ("brief", brief_field(related_name="dependency_heads")),
                ("version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                              related_name="heads", to="macro_persistence.dependencyversion")),
            ],
            options={"db_table": "macro_dependency_heads", "constraints": [
                models.UniqueConstraint(fields=("brief", "role"), name="macro_dependency_head_identity"),
                models.CheckConstraint(condition=models.Q(role__in=ROLES), name="macro_dependency_head_role_allowed"),
            ]},
        ),
        migrations.CreateModel(
            name="AssessmentRecord",
            fields=[
                auto_id(),
                ("assessment_id", models.CharField(max_length=255)),
                ("digest", models.CharField(max_length=64)),
                ("payload", models.TextField()),
                ("status", models.CharField(choices=[("current", "current"), ("superseded", "superseded")], max_length=16)),
                ("reasons", models.JSONField()),
                ("reassessment_required", models.BooleanField()),
                ("observed_dependencies", models.JSONField()),
                ("saved_at", models.DateTimeField()),
                ("brief", brief_field(related_name="assessments")),
            ],
            options={"db_table": "macro_assessments", "constraints": [
                models.UniqueConstraint(fields=("brief", "assessment_id"), name="macro_assessment_identity"),
                models.UniqueConstraint(fields=("brief", "id"), name="macro_assessment_scoped_target"),
                models.CheckConstraint(condition=models.Q(assessment_id__regex=r"\S"), name="macro_assessment_id_named"),
                models.CheckConstraint(condition=models.Q(digest__regex=r"^[0-9a-f]{64}$"), name="macro_assessment_digest_sha256"),
                models.CheckConstraint(condition=models.Q(status__in=("current", "superseded")), name="macro_assessment_status_allowed"),
            ]},
        ),
        migrations.CreateModel(
            name="CurrentAssessment",
            fields=[
                ("brief", brief_field(related_name="current_assessment", primary_key=True)),
                ("assessment", assessment_field("current_pointers")),
            ],
            options={"db_table": "macro_current_assessments"},
        ),
        migrations.CreateModel(
            name="BriefVersion",
            fields=[
                auto_id(),
                ("generation", models.PositiveBigIntegerField()),
                ("saved_at", models.DateTimeField()),
                ("brief", brief_field(related_name="versions")),
                ("assessment", assessment_field("brief_versions")),
            ],
            options={"db_table": "macro_brief_versions", "constraints": [
                models.UniqueConstraint(fields=("brief", "generation"), name="macro_brief_version_generation"),
                models.CheckConstraint(condition=models.Q(generation__gt=0), name="macro_brief_version_generation_positive"),
            ]},
        ),
        migrations.CreateModel(
            name="NotificationIntent",
            fields=[
                ("intent_id", models.CharField(max_length=80, primary_key=True, serialize=False)),
                ("state", models.CharField(choices=[("pending", "pending"), ("canceled", "canceled"), ("delivered", "delivered")], default="pending", max_length=16)),
                ("created_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField()),
                ("brief", brief_field(related_name="notification_intents")),
                ("assessment", assessment_field("notification_intents")),
            ],
            options={"db_table": "macro_notification_intents", "constraints": [
                models.CheckConstraint(condition=models.Q(intent_id__regex=r"\S"), name="macro_notification_id_named"),
                models.CheckConstraint(condition=models.Q(state__in=("pending", "canceled", "delivered")), name="macro_notification_state_allowed"),
                models.CheckConstraint(condition=models.Q(updated_at__gte=models.F("created_at")), name="macro_notification_time_order"),
            ], "indexes": [models.Index(fields=["brief", "state"], name="macro_notification_pending_idx")]},
        ),
        migrations.CreateModel(
            name="ReassessmentWork",
            fields=[
                auto_id(),
                ("context_digest", models.CharField(max_length=64)),
                ("reason", models.TextField()),
                ("created_at", models.DateTimeField()),
                ("state", models.CharField(choices=[("pending", "pending"), ("completed", "completed"), ("superseded", "superseded")], default="pending", max_length=16)),
                ("completed_at", models.DateTimeField(null=True)),
                ("brief", brief_field(related_name="reassessment_work")),
            ],
            options={"db_table": "macro_reassessment_work", "constraints": [
                models.UniqueConstraint(fields=("brief", "context_digest"), name="macro_reassessment_context_identity"),
                models.CheckConstraint(condition=models.Q(context_digest__regex=r"^[0-9a-f]{64}$"), name="macro_reassessment_digest_sha256"),
                models.CheckConstraint(condition=models.Q(reason__regex=r"\S"), name="macro_reassessment_reason_named"),
                models.CheckConstraint(condition=(
                    models.Q(state="pending", completed_at__isnull=True)
                    | models.Q(state__in=("completed", "superseded"), completed_at__isnull=False,
                               completed_at__gte=models.F("created_at"))
                ), name="macro_reassessment_completion_state"),
            ]},
        ),
        migrations.CreateModel(
            name="AuditTransition",
            fields=[
                ("sequence", models.BigAutoField(primary_key=True, serialize=False)),
                ("kind", models.CharField(max_length=64)),
                ("happened_at", models.DateTimeField()),
                ("detail", models.JSONField()),
                ("brief", brief_field(related_name="audit_transitions")),
            ],
            options={"db_table": "macro_audit_transitions", "ordering": ("sequence",), "constraints": [
                models.CheckConstraint(condition=models.Q(kind__regex=r"\S"), name="macro_audit_kind_named"),
            ]},
        ),
        migrations.RunSQL(sql=GUARDS_SQL, reverse_sql=REVERSE_GUARDS_SQL),
    ]
