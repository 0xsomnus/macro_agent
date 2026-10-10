from pathlib import Path

from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from macro_agent.monitoring.fixture_loading import fixture_loaders
from macro_agent.monitoring.output import render
from macro_agent.monitoring.runner import recover_job
from macro_agent.scheduling.service import ScheduleConflict, ScheduleUnavailable


class Command(BaseCommand):
    help = ("Explicitly recover an inspected blocked job, preserving every outcome. "
            "Retry may execute unstarted model work within its allowances; "
            "reconcile only reads saved analysis and never repeats a model call.")

    def add_arguments(self, parser):
        parser.add_argument("--owner", required=True)
        parser.add_argument("--slot-id", required=True)
        parser.add_argument("--command-id", required=True, help="New UUID for this recovery; retain it for inert replay")
        parser.add_argument("--expected-token", required=True, help="Last lease token from saved inspection")
        parser.add_argument("--expected-watch-revision", required=True, type=int)
        parser.add_argument("--action", required=True, choices=("retry", "reconcile"))
        parser.add_argument("--reason", required=True)
        parser.add_argument("--fixture-map", type=Path)

    def handle(self, *args, **options):
        try:
            result = recover_job(options["owner"], options["slot_id"], options["command_id"],
                options["expected_token"], options["expected_watch_revision"], options["action"],
                options["reason"], loaders=fixture_loaders(options["fixture_map"]))
        except DatabaseError:
            raise CommandError("Database unavailable; retain the recovery command ID and inspect saved work before continuing") from None
        except (ScheduleConflict, ScheduleUnavailable) as error:
            # Scheduling errors contain authored local reasons, never remote
            # exception bodies, credentials or the operator's supplied reason.
            raise CommandError(str(error)) from None
        except (ValueError, TypeError, PermissionDenied, PermissionError, RuntimeError) as error:
            raise CommandError(f"Recovery unavailable ({type(error).__name__}); inspect the saved job and reviewed watch") from None
        self.stdout.write(render(result))
