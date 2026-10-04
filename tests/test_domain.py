"""Authority, immutable-input and temporal rules without chosen persistence."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from macro_agent.domain.models import (
    CompiledThesisVersion, ContextSnapshot, EventRevision, PinnedDependency,
    UserThesisVersion, VersionedContent, canonical_json, text_digest,
)
from macro_agent.domain.thesis import ApprovalRequest, approve_thesis
from macro_agent.domain.time import (
    SourceTimes, latest_operational_revision, operationally_available,
    parse_instant, publicly_available,
)


AT = parse_instant("2026-10-02T06:00:00Z")


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.raw = "  I expect gold to benefit.\nMy premise needs testing.  "
        self.thesis = UserThesisVersion("thesis-v1", "thesis", "owner", self.raw, AT)
        self.meaning = CompiledThesisVersion("meaning-v1", "thesis-v1", ("real_yields",), "months", ("Persistently higher real yields",), AT)
        self.request = ApprovalRequest(
            "approval-v1", "owner", "user", "thesis-v1", self.thesis.text_digest,
            "meaning-v1", self.meaning.digest, AT,
        )

    def test_approval_preserves_exact_bytes_and_meaning(self):
        result = approve_thesis(self.thesis, self.meaning, self.request, now=AT)
        self.assertEqual(self.thesis.exact_text, self.raw)
        self.assertEqual(result.text_digest, hashlib.sha256(self.raw.encode("utf-8")).hexdigest())
        self.assertEqual(result.interpretation_digest, self.meaning.digest)
        self.assertNotEqual(self.thesis.text_digest, text_digest(self.raw.strip()))
        with self.assertRaises(FrozenInstanceError):
            self.thesis.exact_text = "Changed by worker"

    def test_same_owner_worker_and_other_user_cannot_approve(self):
        for actor, role in (("owner", "worker"), ("other-owner", "user")):
            with self.subTest(actor=actor, role=role), self.assertRaises(PermissionError):
                approve_thesis(self.thesis, self.meaning, replace(self.request, actor_id=actor, actor_role=role), now=AT)

    def test_material_recompile_needs_new_exact_approval(self):
        changed = replace(self.meaning, version_id="meaning-v2", drivers=("central_bank_buying",))
        with self.assertRaises(ValueError):
            approve_thesis(self.thesis, changed, self.request, now=AT)
        approved = approve_thesis(self.thesis, changed, replace(
            self.request, approval_id="approval-v2", interpretation_version_id=changed.version_id,
            interpretation_digest=changed.digest,
        ), now=AT)
        self.assertEqual(approved.interpretation_version_id, "meaning-v2")
        self.assertEqual(self.thesis.exact_text, self.raw)

    def test_interpretation_cannot_be_approved_against_a_different_thesis(self):
        foreign = replace(self.meaning, thesis_version_id="another-thesis-v1")
        request = replace(self.request, interpretation_digest=foreign.digest)
        with self.assertRaises(ValueError):
            approve_thesis(self.thesis, foreign, request, now=AT)

    def test_approved_text_digest_rejects_whitespace_change(self):
        request = replace(self.request, text_digest=text_digest(self.raw.strip()))
        with self.assertRaises(ValueError):
            approve_thesis(self.thesis, self.meaning, request, now=AT)

    def test_approval_time_cannot_be_backdated_or_future_dated(self):
        for difference in (-1, 1):
            with self.subTest(difference=difference), self.assertRaises(ValueError):
                approve_thesis(self.thesis, self.meaning, replace(
                    self.request, approved_at=AT + timedelta(seconds=difference),
                ), now=AT)

    def test_approval_waits_until_both_inputs_are_available(self):
        future = replace(self.meaning, known_at=AT + timedelta(seconds=1))
        with self.assertRaises(ValueError):
            approve_thesis(self.thesis, future, replace(self.request, interpretation_digest=future.digest), now=AT)

    def test_compilation_cannot_predate_the_linked_thesis_version(self):
        earlier = replace(self.meaning, known_at=AT - timedelta(seconds=1))
        with self.assertRaises(ValueError):
            approve_thesis(self.thesis, earlier, replace(self.request, interpretation_digest=earlier.digest), now=AT)

    def test_incomplete_intent_remains_incomplete_rather_than_invented(self):
        incomplete = CompiledThesisVersion("rough-v1", "thesis-v1", (), None, (), AT)
        approved = approve_thesis(self.thesis, incomplete, replace(
            self.request, interpretation_version_id=incomplete.version_id,
            interpretation_digest=incomplete.digest,
        ), now=AT)
        self.assertEqual(approved.interpretation_version_id, "rough-v1")
        self.assertIsNone(incomplete.horizon)
        self.assertEqual(incomplete.drivers, ())


class ImmutableContextTests(unittest.TestCase):
    def test_compiled_values_detach_input_lists(self):
        drivers = ["real_yields"]
        signs = ["Persistently higher real yields"]
        meaning = CompiledThesisVersion("meaning-v1", "thesis-v1", drivers, None, signs, AT)
        drivers.append("unapproved_driver")
        signs.clear()
        self.assertEqual(meaning.drivers, ("real_yields",))
        self.assertEqual(meaning.invalidation_signposts, ("Persistently higher real yields",))

    def test_content_is_canonical_and_deeply_immutable(self):
        content = {"observations": [{"value": 3.1}], "unknowns": ["regime"]}
        record = VersionedContent("macro-v1", "MacroContextVersion", AT, canonical_json(content))
        original_digest = record.digest
        content["observations"][0]["value"] = 99
        decoded = json.loads(record.content_json)
        decoded["unknowns"].clear()
        self.assertEqual(record.digest, original_digest)
        self.assertEqual(json.loads(record.content_json)["observations"][0]["value"], 3.1)
        self.assertEqual(record.content_json, canonical_json(json.loads(record.content_json)))

    def test_snapshot_detaches_list_and_rejects_duplicate_roles(self):
        pin = PinnedDependency("macro_context", "macro-v1", text_digest("macro"), AT)
        source_list = [pin]
        snapshot = ContextSnapshot("snapshot-v1", AT, source_list)
        source_list.clear()
        self.assertEqual(snapshot.dependency("macro_context"), pin)
        with self.assertRaises(ValueError):
            ContextSnapshot("snapshot-v2", AT, (pin, replace(pin, version_id="macro-v2")))

    def test_snapshot_rejects_future_context_even_with_publicly_old_content(self):
        pin = PinnedDependency("macro_context", "macro-v1", text_digest("macro"), AT + timedelta(seconds=1))
        with self.assertRaises(ValueError):
            ContextSnapshot("snapshot-v1", AT, (pin,))

    def test_snapshot_digest_independent_of_dependency_input_order(self):
        a = PinnedDependency("macro_context", "macro-v1", text_digest("macro"), AT)
        b = PinnedDependency("coverage", "coverage-v1", text_digest("coverage"), AT)
        self.assertEqual(ContextSnapshot("snapshot", AT, (a, b)).digest, ContextSnapshot("snapshot", AT, (b, a)).digest)

    def test_nested_non_json_and_non_finite_inputs_are_rejected(self):
        for invalid in ({"bad": float("nan")}, {"bad": float("inf")}, {"bad": (1, 2)}, {1: "bad"}):
            with self.subTest(invalid=invalid), self.assertRaises((ValueError, TypeError)):
                canonical_json(invalid)
        for invalid in ('{"a":1,"a":2}', '{"bad":NaN}', '{"bad":1e9999}', '[]'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                VersionedContent("content-v1", "Evidence", AT, invalid)

    def test_dataclass_annotations_do_not_allow_invalid_runtime_values(self):
        with self.assertRaises(TypeError):
            CompiledThesisVersion("meaning-v1", "thesis-v1", "real_yields", None, (), AT)
        with self.assertRaises(ValueError):
            PinnedDependency("macro_context", "macro-v1", "looks-like-a-hash", AT)
        with self.assertRaises(ValueError):
            EventRevision("release", True, "official", "use-v1", SourceTimes(None, AT, AT), "{}")
        with self.assertRaises(ValueError):
            CompiledThesisVersion("meaning-v1", "thesis-v1", ("driver", "driver"), None, (), AT)


class TimeAndReplayTests(unittest.TestCase):
    def event(self, revision, known_at, *, facts="{}"):
        return EventRevision("release", revision, "official", "use-v1", SourceTimes(AT, known_at, known_at), facts)

    def test_public_backfill_never_becomes_earlier_operational_knowledge(self):
        receipt = AT + timedelta(days=1)
        times = SourceTimes(AT, receipt, receipt + timedelta(seconds=1))
        self.assertTrue(publicly_available(times, AT))
        self.assertFalse(operationally_available(times, AT))
        self.assertFalse(operationally_available(times, receipt))
        self.assertTrue(operationally_available(times, times.known_at))

    def test_unknown_public_availability_is_not_fabricated(self):
        times = SourceTimes(None, AT, AT)
        self.assertFalse(publicly_available(times, AT + timedelta(days=1)))
        self.assertTrue(operationally_available(times, AT))
        self.assertIsNone(times.public_available_at)

    def test_known_at_cannot_precede_receipt(self):
        with self.assertRaises(ValueError):
            SourceTimes(AT, AT + timedelta(seconds=1), AT)

    def test_timezone_normalization_and_rejection_of_naive_instants(self):
        local = datetime(2026, 10, 2, 9, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(SourceTimes(local, local, local).known_at, AT)
        with self.assertRaises(ValueError):
            parse_instant("2026-10-02T06:00:00")
        with self.assertRaises(ValueError):
            UserThesisVersion("v1", "thesis", "owner", "Premise", datetime(2026, 10, 2, 6))

    def test_operational_replay_preserves_original_until_correction_known(self):
        original = self.event(1, AT + timedelta(seconds=5), facts='{"measure":3.1}')
        correction = self.event(2, AT + timedelta(minutes=10), facts='{"measure":3.0}')
        records = (correction, original)
        self.assertIsNone(latest_operational_revision(records, "release", AT))
        self.assertEqual(latest_operational_revision(records, "release", AT + timedelta(seconds=6)), original)
        self.assertEqual(latest_operational_revision(records, "release", correction.times.known_at), correction)

    def test_late_original_does_not_displace_an_already_known_correction(self):
        correction = self.event(2, AT + timedelta(seconds=1))
        late_original = self.event(1, AT + timedelta(seconds=2))
        self.assertEqual(latest_operational_revision((correction, late_original), "release", late_original.times.known_at), correction)

    def test_conflicting_revision_identity_is_rejected(self):
        original = self.event(1, AT, facts='{"measure":3.1}')
        corrupted = replace(original, facts_json='{"measure":99}')
        with self.assertRaises(ValueError):
            latest_operational_revision((original, corrupted), "release", AT)
        self.assertEqual(latest_operational_revision((original, original), "release", AT), original)


if __name__ == "__main__":
    unittest.main()
