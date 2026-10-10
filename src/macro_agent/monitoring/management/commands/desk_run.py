from pathlib import Path
from time import sleep

from django.db import DatabaseError
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from macro_agent.monitoring.fixture_loading import fixture_loaders
from macro_agent.monitoring.output import render
from macro_agent.monitoring.runner import run_tick


class Command(BaseCommand):
    help = "Run separate bounded internal capture or analytical process ticks"

    def add_arguments(self, parser):
        parser.add_argument("--owner", required=True)
        parser.add_argument("--watch-id", required=True)
        parser.add_argument("--role", choices=("capture", "analysis"), required=True)
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--idle-seconds", type=float)
        parser.add_argument("--max-ticks", type=int)
        parser.add_argument("--fixture-map", type=Path)

    def handle(self, *args, **options):
        once, idle, maximum = options["once"], options["idle_seconds"], options["max_ticks"]
        if not once and (idle is None or not 0.1 <= idle <= 60):
            raise CommandError("Continuous operation needs --idle-seconds between 0.1 and 60")
        if maximum is not None and maximum < 1:
            raise CommandError("--max-ticks must be positive")
        try:
            loaders = fixture_loaders(options["fixture_map"])
        except ValueError as error:
            raise CommandError(str(error)) from None
        count = 0
        try:
            while True:
                try:
                    result = run_tick(options["owner"], options["watch_id"], options["role"], loaders=loaders)
                except DatabaseError as error:
                    # The saved lease remains recoverable after database trouble.
                    result = {"status": "database_unavailable", "code": type(error).__name__}
                    if once:
                        raise CommandError("Database unavailable; saved leases remain inspectable after recovery") from None
                except (ValueError, TypeError) as error:
                    raise CommandError(str(error)) from None
                except (PermissionDenied, PermissionError, RuntimeError) as error:
                    raise CommandError(f"Runner requires review ({type(error).__name__})") from None
                self.stdout.write(render(result))
                count += 1
                if once or (maximum is not None and count >= maximum):
                    break
                sleep(idle)
        except KeyboardInterrupt:
            self.stdout.write("Stopped. Saved work and uncertain outcomes remain available for inspection.")
