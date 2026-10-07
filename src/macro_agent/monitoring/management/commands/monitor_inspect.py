from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from macro_agent.monitoring.inspection import inspect_source
from macro_agent.monitoring.models import SourceState
from macro_agent.monitoring.output import render, save_new


class Command(BaseCommand):
    help = "Inspect a coherent read-only capture/work trace"

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True)
        parser.add_argument("--output")

    def handle(self, *args, **options):
        try:
            payload = inspect_source(options["source"])
            text = render(payload)
            if options["output"]:
                save_new(options["output"], text)
        except (PermissionDenied, ValueError, OSError, SourceState.DoesNotExist) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(text)
