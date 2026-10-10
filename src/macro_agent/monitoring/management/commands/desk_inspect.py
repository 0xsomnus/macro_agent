from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError

from macro_agent.desk.service import inspect_review
from macro_agent.monitoring.output import render
from macro_agent.scheduling.service import inspect_watch
from macro_agent.scheduling.diagnostics import render_brief, summarize_watch


class Command(BaseCommand):
    help = "Read saved watch or review state without capture, catalogue or inference"

    def add_arguments(self, parser):
        parser.add_argument("--owner", required=True)
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--watch-id")
        group.add_argument("--review-id")
        parser.add_argument("--brief", action="store_true", help="Summarize a watch's saved jobs and failure codes")

    def handle(self, *args, **options):
        if options.get("brief") and not options.get("watch_id"):
            raise CommandError("--brief requires --watch-id")
        try:
            result = (inspect_watch(options["owner"], options["watch_id"]) if options["watch_id"]
                      else inspect_review(options["owner"], options["review_id"]))
            output = render_brief(summarize_watch(result)) if options.get("brief") else render(result)
        except (ValueError, TypeError, PermissionError, PermissionDenied, RuntimeError, DatabaseError) as error:
            raise CommandError(f"Inspection unavailable ({type(error).__name__})") from None
        self.stdout.write(output)
