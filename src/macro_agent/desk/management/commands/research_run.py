"""One explicitly enrolled research job, using durable due times and leases."""

from time import sleep

from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from macro_agent.desk import research_jobs
from macro_agent.monitoring.output import render
from macro_agent.theses import compilation, service


class Command(BaseCommand):
    help = "Resume one explicitly enrolled internal investigation when its saved work is due"

    def add_arguments(self, parser):
        parser.add_argument("--owner", required=True)
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--idle-seconds", type=float)
        parser.add_argument("--max-ticks", type=int)

    def handle(self, *args, **options):
        once, idle, maximum = options["once"], options["idle_seconds"], options["max_ticks"]
        if not once and (idle is None or not 1 <= idle <= 60):
            raise CommandError("Continuous operation needs --idle-seconds between 1 and 60")
        if maximum is not None and maximum < 1:
            raise CommandError("--max-ticks must be positive")
        ticks = 0
        try:
            while True:
                try:
                    result = research_jobs.run_tick(options["owner"], options["run_id"])
                except DatabaseError:
                    # No retry inside an uncertain operation. A later tick
                    # reconciles its saved research admission and exact lease.
                    if once:
                        raise CommandError("Database unavailable. Inspect saved research before recovery.") from None
                    result = {"status": "database_unavailable"}
                except (ValueError, TypeError, PermissionDenied, PermissionError,
                        compilation.CompilationDisabled, compilation.CompilationUnavailable,
                        service.ThesisConflict, service.ThesisUnavailable) as error:
                    raise CommandError("Research worker needs review (" + type(error).__name__ + ")") from None
                self.stdout.write(render(result))
                ticks += 1
                state = result.get("job", {}).get("status")
                if once or state in {"blocked", "completed", "revoked"} or (maximum is not None and ticks >= maximum):
                    break
                sleep(idle)
        except KeyboardInterrupt:
            self.stdout.write("Stopped. Saved research and uncertain outcomes remain available for inspection.")
