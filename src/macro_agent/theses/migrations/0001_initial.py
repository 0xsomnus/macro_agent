"""Durable thesis records with PostgreSQL scope and history protections.

Generated model operations use Django 5.2.17. Explicit SQL guards ordinary
writes, including queryset and raw SQL mutations. It does not authenticate the
caller or substitute for the application's owner-then-thesis locking protocol.
"""

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


IMMUTABLE_TABLES = (
    "macro_thesis_text_versions", "macro_thesis_interpretations",
    "macro_thesis_approvals", "macro_thesis_command_receipts",
    "macro_thesis_audit_transitions",
)
SCOPED_CONSTRAINTS = (
    ("macro_thesis_text_versions", "macro_text_parent_scope_fk",
     "(thesis_id, parent_id)", "macro_thesis_text_versions", "(thesis_id, id)"),
    ("macro_thesis_interpretations", "macro_interp_text_scope_fk",
     "(thesis_id, text_version_id)", "macro_thesis_text_versions", "(thesis_id, id)"),
    ("macro_thesis_approvals", "macro_approval_text_scope_fk",
     "(thesis_id, text_version_id)", "macro_thesis_text_versions", "(thesis_id, id)"),
    ("macro_thesis_approvals", "macro_approval_interp_text_fk",
     "(thesis_id, text_version_id, interpretation_id)", "macro_thesis_interpretations",
     "(thesis_id, text_version_id, id)"),
    ("macro_thesis_approvals", "macro_approval_owner_scope_fk",
     "(thesis_id, actor_id)", "macro_theses", "(id, owner_id)"),
    ("macro_thesis_command_receipts", "macro_command_owner_scope_fk",
     "(thesis_id, owner_id)", "macro_theses", "(id, owner_id)"),
    ("macro_theses", "macro_latest_text_scope_fk",
     "(id, latest_text_id)", "macro_thesis_text_versions", "(thesis_id, id)"),
    ("macro_theses", "macro_latest_interp_scope_fk",
     "(id, latest_interpretation_id)", "macro_thesis_interpretations", "(thesis_id, id)"),
    ("macro_theses", "macro_latest_draft_text_interp_fk",
     "(id, latest_text_id, latest_interpretation_id)", "macro_thesis_interpretations",
     "(thesis_id, text_version_id, id)"),
    ("macro_theses", "macro_current_approval_scope_fk",
     "(id, current_approval_id)", "macro_thesis_approvals", "(thesis_id, id)"),
)

GUARDS_SQL = """
CREATE FUNCTION macro_thesis_reject_history_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'immutable thesis history: %', TG_TABLE_NAME USING ERRCODE = '23514';
END;
$$;

CREATE FUNCTION macro_thesis_guard_identity_and_progress() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'durable thesis cannot be deleted' USING ERRCODE = '23514';
    END IF;
    IF ROW(NEW.id, NEW.owner_id, NEW.created_at)
       IS DISTINCT FROM ROW(OLD.id, OLD.owner_id, OLD.created_at) THEN
        RAISE EXCEPTION 'thesis identity, owner, and creation time are immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.revision < OLD.revision THEN
        RAISE EXCEPTION 'thesis revision cannot move backwards' USING ERRCODE = '23514';
    END IF;
    IF NEW.changed_at < OLD.changed_at THEN
        RAISE EXCEPTION 'thesis changed_at cannot move backwards' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER macro_thesis_identity_progress_guard
BEFORE UPDATE OR DELETE ON macro_theses
FOR EACH ROW EXECUTE FUNCTION macro_thesis_guard_identity_and_progress();

CREATE FUNCTION macro_thesis_is_string_array(value jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT CASE WHEN jsonb_typeof(value) = 'array' THEN
        NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(value) AS entries(element)
            WHERE jsonb_typeof(element) <> 'string'
        )
    ELSE FALSE END;
$$;
ALTER TABLE macro_thesis_interpretations ADD CONSTRAINT macro_interp_drivers_strings
    CHECK (macro_thesis_is_string_array(drivers));
ALTER TABLE macro_thesis_interpretations ADD CONSTRAINT macro_interp_signposts_strings
    CHECK (macro_thesis_is_string_array(invalidation_signposts));
ALTER TABLE macro_thesis_command_receipts ADD CONSTRAINT macro_command_result_object
    CHECK (jsonb_typeof(result) = 'object');
ALTER TABLE macro_thesis_audit_transitions ADD CONSTRAINT macro_thesis_audit_detail_object
    CHECK (jsonb_typeof(detail) = 'object');
"""
for table in IMMUTABLE_TABLES:
    GUARDS_SQL += f"""
CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}
FOR EACH ROW EXECUTE FUNCTION macro_thesis_reject_history_change();
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
ALTER TABLE macro_thesis_audit_transitions DROP CONSTRAINT macro_thesis_audit_detail_object;
ALTER TABLE macro_thesis_command_receipts DROP CONSTRAINT macro_command_result_object;
ALTER TABLE macro_thesis_interpretations DROP CONSTRAINT macro_interp_signposts_strings;
ALTER TABLE macro_thesis_interpretations DROP CONSTRAINT macro_interp_drivers_strings;
DROP FUNCTION macro_thesis_is_string_array(jsonb);
DROP TRIGGER macro_thesis_identity_progress_guard ON macro_theses;
DROP FUNCTION macro_thesis_guard_identity_and_progress();
DROP FUNCTION macro_thesis_reject_history_change();
"""


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TextVersionRecord',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('exact_text', models.TextField()),
                ('text_digest', models.CharField(max_length=64)),
                ('created_at', models.DateTimeField()),
                ('parent', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='children', to='macro_theses.textversionrecord')),
            ],
            options={
                'db_table': 'macro_thesis_text_versions',
            },
        ),
        migrations.CreateModel(
            name='InterpretationRecord',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('drivers', models.JSONField()),
                ('horizon', models.TextField(null=True)),
                ('invalidation_signposts', models.JSONField()),
                ('known_at', models.DateTimeField()),
                ('digest', models.CharField(max_length=64)),
                ('origin', models.CharField(choices=[('user_supplied', 'user_supplied')], default='user_supplied', editable=False, max_length=32)),
                ('text_version', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='interpretations', to='macro_theses.textversionrecord')),
            ],
            options={
                'db_table': 'macro_thesis_interpretations',
            },
        ),
        migrations.CreateModel(
            name='ApprovalRecord',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('approved_at', models.DateTimeField()),
                ('digest', models.CharField(max_length=64)),
                ('revision', models.PositiveBigIntegerField()),
                ('actor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='macro_thesis_approvals', to=settings.AUTH_USER_MODEL)),
                ('interpretation', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='approvals', to='macro_theses.interpretationrecord')),
                ('text_version', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='approvals', to='macro_theses.textversionrecord')),
            ],
            options={
                'db_table': 'macro_thesis_approvals',
            },
        ),
        migrations.CreateModel(
            name='ThesisRecord',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('revision', models.PositiveBigIntegerField(default=0)),
                ('created_at', models.DateTimeField()),
                ('changed_at', models.DateTimeField()),
                ('current_approval', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='macro_theses.approvalrecord')),
                ('latest_interpretation', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='macro_theses.interpretationrecord')),
                ('latest_text', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='macro_theses.textversionrecord')),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='macro_theses', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'macro_theses',
            },
        ),
        migrations.AddField(
            model_name='textversionrecord',
            name='thesis',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='text_versions', to='macro_theses.thesisrecord'),
        ),
        migrations.AddField(
            model_name='interpretationrecord',
            name='thesis',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='interpretations', to='macro_theses.thesisrecord'),
        ),
        migrations.CreateModel(
            name='CommandReceipt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('command_id', models.UUIDField()),
                ('kind', models.CharField(choices=[('create', 'create'), ('propose', 'propose'), ('approve', 'approve')], max_length=16)),
                ('request_digest', models.CharField(max_length=64)),
                ('result', models.JSONField()),
                ('saved_at', models.DateTimeField()),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='macro_thesis_commands', to=settings.AUTH_USER_MODEL)),
                ('thesis', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='command_receipts', to='macro_theses.thesisrecord')),
            ],
            options={
                'db_table': 'macro_thesis_command_receipts',
            },
        ),
        migrations.CreateModel(
            name='AuditTransition',
            fields=[
                ('sequence', models.BigAutoField(primary_key=True, serialize=False)),
                ('kind', models.CharField(max_length=64)),
                ('at', models.DateTimeField()),
                ('detail', models.JSONField()),
                ('thesis', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='audit_transitions', to='macro_theses.thesisrecord')),
            ],
            options={
                'db_table': 'macro_thesis_audit_transitions',
                'ordering': ('sequence',),
            },
        ),
        migrations.AddField(
            model_name='approvalrecord',
            name='thesis',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='approvals', to='macro_theses.thesisrecord'),
        ),
        migrations.AddConstraint(
            model_name='thesisrecord',
            constraint=models.UniqueConstraint(fields=('id', 'owner'), name='macro_thesis_owner_target'),
        ),
        migrations.AddConstraint(
            model_name='thesisrecord',
            constraint=models.CheckConstraint(condition=models.Q(('revision__gte', 0)), name='macro_thesis_revision_nonnegative'),
        ),
        migrations.AddConstraint(
            model_name='thesisrecord',
            constraint=models.CheckConstraint(condition=models.Q(('changed_at__gte', models.F('created_at'))), name='macro_thesis_time_order'),
        ),
        migrations.AddConstraint(
            model_name='thesisrecord',
            constraint=models.CheckConstraint(condition=(
                models.Q(latest_text__isnull=True, latest_interpretation__isnull=True,
                         current_approval__isnull=True)
                | models.Q(latest_text__isnull=False, latest_interpretation__isnull=False)
            ), name='macro_thesis_draft_pair'),
        ),
        migrations.AddConstraint(
            model_name='textversionrecord',
            constraint=models.UniqueConstraint(fields=('thesis', 'id'), name='macro_text_scoped_target'),
        ),
        migrations.AddConstraint(
            model_name='textversionrecord',
            constraint=models.CheckConstraint(condition=models.Q(('exact_text__regex', '\\S')), name='macro_text_named'),
        ),
        migrations.AddConstraint(
            model_name='textversionrecord',
            constraint=models.CheckConstraint(condition=models.Q(('text_digest__regex', '^[0-9a-f]{64}$')), name='macro_text_digest_sha256'),
        ),
        migrations.AddConstraint(
            model_name='textversionrecord',
            constraint=models.CheckConstraint(condition=models.Q(('parent', models.F('id')), _negated=True), name='macro_text_parent_not_self'),
        ),
        migrations.AddConstraint(
            model_name='interpretationrecord',
            constraint=models.UniqueConstraint(fields=('thesis', 'id'), name='macro_interp_scoped_target'),
        ),
        migrations.AddConstraint(
            model_name='interpretationrecord',
            constraint=models.UniqueConstraint(fields=('thesis', 'text_version', 'id'), name='macro_interp_text_target'),
        ),
        migrations.AddConstraint(
            model_name='interpretationrecord',
            constraint=models.CheckConstraint(condition=models.Q(('digest__regex', '^[0-9a-f]{64}$')), name='macro_interp_digest_sha256'),
        ),
        migrations.AddConstraint(
            model_name='interpretationrecord',
            constraint=models.CheckConstraint(condition=models.Q(('origin', 'user_supplied')), name='macro_interp_origin_manual'),
        ),
        migrations.AddConstraint(
            model_name='commandreceipt',
            constraint=models.UniqueConstraint(fields=('owner', 'command_id'), name='macro_thesis_command_identity'),
        ),
        migrations.AddConstraint(
            model_name='commandreceipt',
            constraint=models.CheckConstraint(condition=models.Q(('kind__in', ('create', 'propose', 'approve'))), name='macro_thesis_command_kind_allowed'),
        ),
        migrations.AddConstraint(
            model_name='commandreceipt',
            constraint=models.CheckConstraint(condition=models.Q(('request_digest__regex', '^[0-9a-f]{64}$')), name='macro_command_digest_sha256'),
        ),
        migrations.AddConstraint(
            model_name='audittransition',
            constraint=models.CheckConstraint(condition=models.Q(('kind__regex', '\\S')), name='macro_thesis_audit_kind_named'),
        ),
        migrations.AddConstraint(
            model_name='approvalrecord',
            constraint=models.UniqueConstraint(fields=('thesis', 'id'), name='macro_approval_scoped_target'),
        ),
        migrations.AddConstraint(
            model_name='approvalrecord',
            constraint=models.UniqueConstraint(fields=('thesis', 'revision'), name='macro_approval_revision_identity'),
        ),
        migrations.AddConstraint(
            model_name='approvalrecord',
            constraint=models.CheckConstraint(condition=models.Q(('digest__regex', '^[0-9a-f]{64}$')), name='macro_approval_digest_sha256'),
        ),
        migrations.AddConstraint(
            model_name='approvalrecord',
            constraint=models.CheckConstraint(condition=models.Q(('revision__gt', 0)), name='macro_approval_revision_positive'),
        ),
        migrations.RunSQL(sql=GUARDS_SQL, reverse_sql=REVERSE_GUARDS_SQL),
    ]
