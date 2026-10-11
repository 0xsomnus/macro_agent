"""Explicit local one-off publication; no watch enrollment or external send."""

from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from macro_agent.desk import publication
from macro_agent.monitoring.output import render
from macro_agent.theses.service import ThesisUnavailable


class Command(BaseCommand):
    help = "Preview or explicitly publish one retained daily review internally"

    def add_arguments(self, parser):
        parser.add_argument("--owner", required=True)
        parser.add_argument("--review-id", required=True)
        parser.add_argument("--fanout-limit", required=True, type=int)
        parser.add_argument("--preview", action="store_true")
        parser.add_argument("--command-id")
        parser.add_argument("--expected-generation", type=int)
        parser.add_argument("--expected-review-digest")

    def handle(self, *args, **options):
        try:
            command_fields = (options["command_id"], options["expected_generation"],
                              options["expected_review_digest"])
            if options["preview"]:
                if any(value is not None for value in command_fields):
                    raise ValueError("Preview does not accept publication command fields")
                result = publication.preview_publication(options["owner"], options["review_id"],
                                                         options["fanout_limit"])
            else:
                if any(value is None for value in command_fields):
                    raise ValueError("Publishing requires --command-id, --expected-generation and --expected-review-digest")
                result = publication.publish_review(options["owner"], options["review_id"],
                    options["command_id"], options["expected_review_digest"],
                    options["expected_generation"], options["fanout_limit"])
        except (ValueError, TypeError) as error:
            raise CommandError(str(error)) from None
        except (PermissionDenied, PermissionError, ThesisUnavailable, RuntimeError, DatabaseError) as error:
            raise CommandError(f"Daily publication unavailable ({type(error).__name__})") from None
        self.stdout.write(render(result))
