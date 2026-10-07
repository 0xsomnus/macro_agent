from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from macro_agent.monitoring.output import render
from macro_agent.monitoring.work import work_once


class Command(BaseCommand):
    help = "Process a bounded number of durable records; relevance remains explicitly unresolved"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10)
        parser.add_argument("--lease-seconds", type=int, default=30)

    def handle(self, *args, **options):
        try:
            result = work_once(limit=options["limit"], lease_seconds=options["lease_seconds"])
        except (PermissionDenied, ValueError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(render({"processed": len(result), "results": result, "model_calls": 0}))
