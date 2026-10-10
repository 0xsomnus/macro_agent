from dataclasses import asdict
import re

from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from macro_agent.monitoring.capture import CaptureBusy, CaptureFenced, capture
from macro_agent.monitoring.output import render
from macro_agent.monitoring.sources import SourceError, fetch_source, load_recorded, source_specs


class Command(BaseCommand):
    help = "Capture one bounded source snapshot; leave processing as durable pending work"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--source", choices=tuple(source_specs))
        group.add_argument("--fixture")
        parser.add_argument("--fixture-source", default="fixture-monitor")

    def handle(self, *args, **options):
        if options["fixture"]:
            source_id = options["fixture_source"]
            if not re.fullmatch(r"fixture-[a-z0-9][a-z0-9-]{0,63}", source_id):
                raise CommandError("Fixture source must be a bounded fixture- name")
            contract = {"label": "Fictional monitoring feed", "kind": "fictional_fixture",
                "adapter_version": "recorded-json-v1", "rights": "repository fictional fixture",
                "coverage": "bounded_snapshot", "max_items": 100, "max_bytes": 1048576}
            loader = lambda: load_recorded(options["fixture"])
        else:
            source_id = options["source"]
            contract = asdict(source_specs[source_id])
            contract.update(adapter_version="rss-v1", coverage="bounded_snapshot")
            loader = lambda: fetch_source(source_id)
        try:
            result = capture(source_id, contract, loader)
        except (PermissionDenied, PermissionError, CaptureBusy, CaptureFenced, SourceError, ValueError, OSError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(render({"source_id": source_id, "capture_id": str(result.attempt_id),
            "status": result.status, "code": result.code, "items": result.item_count,
            "new_revisions": result.new_revision_count, "processing": "separate_monitor_work_command"}))
        if result.status != "captured":
            raise CommandError("Capture failed; attempt evidence retained, inspect source health")
