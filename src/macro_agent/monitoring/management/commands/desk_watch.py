"""Local operator enrollment, distinct from the session-based trader CLI."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError

from macro_agent.domain.models import normalize_json_object
from macro_agent.monitoring.output import render
from macro_agent.monitoring.runner import enrollment_preview
from macro_agent.scheduling.service import configure_watch


class Command(BaseCommand):
    help = "Preview committed inputs or save an explicit internal watch configuration"

    def add_arguments(self, parser):
        parser.add_argument("--owner", required=True)
        parser.add_argument("--thesis-id", required=True)
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--preview", action="store_true")
        group.add_argument("--config", type=Path)
        parser.add_argument("--command-id")
        parser.add_argument("--expected-revision", type=int)

    def handle(self, *args, **options):
        try:
            if options["preview"]:
                result = enrollment_preview(options["owner"], options["thesis_id"])
            else:
                import json
                path = options["config"]
                if path.stat().st_size > 262_144:
                    raise ValueError("Watch configuration exceeds the local input bound")
                if options["command_id"] is None or options["expected_revision"] is None:
                    raise ValueError("Configuration needs --command-id and --expected-revision")
                config = json.loads(normalize_json_object(path.read_text(encoding="utf-8")))
                result = configure_watch(options["owner"], options["thesis_id"], options["command_id"],
                                         options["expected_revision"], config)
        except (ValueError, TypeError) as error:
            raise CommandError(str(error)) from None
        except (PermissionDenied, PermissionError, RuntimeError, OSError, DatabaseError) as error:
            raise CommandError(f"Watch configuration unavailable ({type(error).__name__})") from None
        self.stdout.write(render(result))
