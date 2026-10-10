from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError

from macro_agent.desk.service import inspect_review
from macro_agent.monitoring.output import render
from macro_agent.scheduling.service import inspect_watch


class Command(BaseCommand):
    help = "Read saved watch or review state without capture, catalogue or inference"

    def add_arguments(self, parser):
        parser.add_argument("--owner", required=True)
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--watch-id")
        group.add_argument("--review-id")

    def handle(self, *args, **options):
        try:
            result = (inspect_watch(options["owner"], options["watch_id"]) if options["watch_id"]
                      else inspect_review(options["owner"], options["review_id"]))
        except (ValueError, TypeError, PermissionError, PermissionDenied, RuntimeError, DatabaseError) as error:
            raise CommandError(f"Inspection unavailable ({type(error).__name__})") from None
        self.stdout.write(render(result))
