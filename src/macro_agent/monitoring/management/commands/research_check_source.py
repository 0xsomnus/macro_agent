"""Check the bounded research source without starting a paid research graph."""

import json
import time

from django.core.management.base import BaseCommand, CommandError

from macro_agent.monitoring import gdelt_research
from macro_agent.monitoring.sources import SourceError


class Command(BaseCommand):
    help = "Check one GDELT metadata query without models, database writes or retries"
    requires_system_checks = []
    requires_migrations_checks = False

    def add_arguments(self, parser):
        parser.add_argument("--query", required=True)

    def handle(self, *args, **options):
        started = time.monotonic()
        result = {"source": "gdelt_research_metadata", "status": "unavailable",
            "code": None, "model_calls": 0, "database_writes": 0,
            "article_fetches": 0, "coverage_complete": False}
        try:
            search = gdelt_research.discover(options["query"])
        except PermissionError:
            result["code"] = "internal_research_disabled"
        except ValueError:
            result["code"] = "invalid_query"
        except SourceError as error:
            # SourceError carries a category only. Never serialize an exception
            # message, remote response body, query or credential here.
            result["code"] = error.code
        else:
            result.update(status="parsed", code="metadata_parsed",
                returned_candidates=search.metadata["returned_candidate_count"],
                selected_reports=search.metadata["selected_count"],
                candidate_cap_reached=search.metadata["candidate_cap_reached"],
                received_at=search.batch.received_at.isoformat(),
                transport_digest=search.batch.transport_digest)
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        self.stdout.write(json.dumps(result, sort_keys=True))
        if result["status"] != "parsed":
            raise CommandError("Research source check failed; no model call or database write was made.")
