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
        parser.add_argument("--recovery-policy", action="store_true",
            help="Check the reviewed 20-second source policy instead of the legacy 10-second policy")

    def handle(self, *args, **options):
        started = time.monotonic()
        result = {"source": "gdelt_research_metadata", "status": "unavailable",
            "code": None, "model_calls": 0, "database_writes": 0,
            "article_fetches": 0, "coverage_complete": False}
        try:
            policy = {"policy_version": gdelt_research.RECOVERY_POLICY_VERSION} if options["recovery_policy"] else {}
            search = gdelt_research.discover(options["query"], **policy)
        except PermissionError:
            result["code"] = "internal_research_disabled"
        except ValueError:
            result["code"] = "invalid_query"
        except SourceError as error:
            # SourceError carries a category only. Never serialize an exception
            # message, remote response body, query or credential here.
            result["code"] = error.code
            if error.retry_after_seconds is not None:
                result["retry_after_seconds"] = error.retry_after_seconds
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
