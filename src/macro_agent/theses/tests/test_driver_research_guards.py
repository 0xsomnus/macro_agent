"""Research profile provenance rejects detached packets and mismatched versions."""

from copy import deepcopy
import json
from uuid import uuid4

from django.db import IntegrityError, transaction
from django.test import TransactionTestCase, override_settings

from macro_agent.desk.tests.test_research_evidence import EvidenceFixtures
from macro_agent.domain import research_compilation, sourced_compilation
from macro_agent.theses import service
from macro_agent.theses.models import CompilationAttempt, InterpretationRecord

from . import test_sourced_compilation as sourced


class ResearchProvider(sourced.SourcedProvider):
    def complete(self, model_id, messages):
        result = super().complete(model_id, messages)
        document = json.loads(result["content"])
        document.update(proposed_drivers=[], exposure_candidates=[])
        result["content"] = json.dumps(document)
        return result


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ALLOW_SYNTHETIC_SETUP=True, MACRO_ENABLE_MODEL_COMPILATION=True,
    MACRO_MODEL_PROVIDER="nanogpt", MACRO_MODEL_API_KEY="recorded-test-key",
    SETTINGS_MODULE="macro_agent.web.local_settings")
class DriverResearchGuardTests(EvidenceFixtures, TransactionTestCase):
    setUp = sourced.SourcedCompilationPersistenceTests.setUp
    compile = sourced.SourcedCompilationPersistenceTests.compile

    def research(self):
        self.provider = ResearchProvider()
        response = self.compile(driver_review=True)
        self.assertEqual(response["compilation"]["status"], "compiled")
        return response

    def clone(self, original, *, configuration, detach=False):
        attempt = deepcopy(original)
        attempt.pk = uuid4()
        attempt.command_id = uuid4()
        attempt.configuration = configuration
        if detach:
            attempt.evidence_context_id = None
        attempt.save(force_insert=True)

    def test_source_v2_schema_or_prompt_cannot_admit_without_a_retained_packet(self):
        self.research()
        original = CompilationAttempt.objects.get()
        configurations = (
            {**original.configuration, "context": "text_only"},
            {key: value for key, value in original.configuration.items() if key != "context"},
            {"context": "text_only", "schema_version": research_compilation.SOURCED_SCHEMA_VERSION},
            {"context": "text_only", "prompt_version": research_compilation.PROMPT_VERSION},
            {"schema_version": None, "prompt_version": research_compilation.PROMPT_VERSION},
        )
        for configuration in configurations:
            with self.subTest(configuration=configuration), self.assertRaises(IntegrityError), transaction.atomic():
                self.clone(original, configuration=configuration, detach=True)
        self.assertEqual(CompilationAttempt.objects.count(), 1)

    def test_retained_packet_requires_one_explicit_supported_schema_prompt_pair(self):
        self.research()
        original = CompilationAttempt.objects.get()
        pairs = (
            (research_compilation.SOURCED_SCHEMA_VERSION, sourced_compilation.PROMPT_VERSION),
            (sourced_compilation.SOURCED_SCHEMA_VERSION, research_compilation.PROMPT_VERSION),
            (None, research_compilation.PROMPT_VERSION),
            (research_compilation.SOURCED_SCHEMA_VERSION, None),
            (None, None),
            ("unknown-schema", "unknown-prompt"),
        )
        for schema, prompt in pairs:
            configuration = {**original.configuration, "schema_version": schema, "prompt_version": prompt}
            with self.subTest(schema=schema, prompt=prompt), self.assertRaises(IntegrityError), transaction.atomic():
                self.clone(original, configuration=configuration)
        self.assertEqual(CompilationAttempt.objects.count(), 1)

    def test_v3_card_reconstruction_rejects_legacy_or_missing_pinned_profile(self):
        response = self.research()
        item = InterpretationRecord.objects.select_related("compilation", "text_version").get(
            pk=response["compilation"]["interpretation_version_id"])
        self.assertEqual(item.review_card["schema_version"], research_compilation.CARD_SCHEMA_VERSION)
        self.assertEqual(service.interpretation_value(item).digest,
                         response["thesis"]["draft"]["interpretation"]["digest"])
        original = deepcopy(item.compilation.configuration)
        configurations = (
            {**original, "schema_version": sourced_compilation.SOURCED_SCHEMA_VERSION,
             "prompt_version": sourced_compilation.PROMPT_VERSION},
            {**original, "context": "text_only"},
            {**original, "schema_version": None},
            {**original, "prompt_version": None},
        )
        for configuration in configurations:
            # Immutable persisted rows stay untouched. Exercise reconstruction
            # with an inconsistent related instance as a guard regression.
            item.compilation.configuration = configuration
            with self.subTest(configuration=configuration), self.assertRaisesMessage(
                    service.ThesisConflict, "pinned compilation profile"):
                service.interpretation_value(item)
        persisted = CompilationAttempt.objects.get(pk=item.compilation_id)
        self.assertEqual(persisted.configuration, original)

    def test_legacy_sourced_profile_and_card_still_reconstruct_without_upgrading(self):
        response = self.compile()
        self.assertEqual(response["compilation"]["status"], "compiled")
        item = InterpretationRecord.objects.select_related("compilation", "text_version").get(
            pk=response["compilation"]["interpretation_version_id"])
        self.assertEqual(item.review_card["schema_version"], sourced_compilation.CARD_SCHEMA_VERSION)
        self.assertEqual(item.compilation.configuration["schema_version"], sourced_compilation.SOURCED_SCHEMA_VERSION)
        self.assertEqual(service.interpretation_value(item).digest,
                         response["thesis"]["draft"]["interpretation"]["digest"])
        item.compilation.configuration = {**item.compilation.configuration,
            "schema_version": research_compilation.SOURCED_SCHEMA_VERSION,
            "prompt_version": research_compilation.PROMPT_VERSION}
        with self.assertRaisesMessage(service.ThesisConflict, "pinned compilation profile"):
            service.interpretation_value(item)
