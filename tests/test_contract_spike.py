import copy
import json
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from contract_spike import DeskSpike, accumulated, digest, load_fixture, materiality, reference_trace


class DeskCase(unittest.TestCase):
    def setUp(self):
        self.fixture = load_fixture()
        self.desk = DeskSpike(self.fixture)
        self.thesis, self.meaning = self.fixture["thesis"], self.fixture["interpretation"]
        self.desk.approve(self.meaning, self.thesis["owner_id"], "user", self.thesis["approved_at"], digest(self.thesis["text"]), digest(self.meaning))

    def tearDown(self):
        self.desk.db.close()


class AuthorityAndTimeTests(DeskCase):
    def test_worker_and_other_user_cannot_activate_changed_meaning(self):
        changed = dict(self.meaning, id="compiled-v2", drivers=["central_bank_buying"])
        for actor, role in ((self.thesis["owner_id"], "worker"), ("other-user", "user")):
            with self.assertRaises(PermissionError):
                self.desk.approve(changed, actor, role, "2026-10-02T06:10:00Z", digest(self.thesis["text"]), digest(changed))
        self.assertEqual(self.desk.active_at("2026-10-02T06:15:00Z"), self.meaning["id"])
        self.assertEqual(self.desk.db.execute("SELECT text FROM theses").fetchone()[0], self.thesis["text"])

    def test_approval_binds_exact_displayed_text_and_meaning(self):
        changed = dict(self.meaning, id="compiled-v2", horizon="one day")
        with self.assertRaises(ValueError):
            self.desk.approve(changed, self.thesis["owner_id"], "user", "2026-10-02T06:10:00Z", digest(self.thesis["text"]), digest(self.meaning))
        self.desk.approve(changed, self.thesis["owner_id"], "user", "2026-10-02T06:10:00Z", digest(self.thesis["text"]), digest(changed))
        self.assertEqual(self.desk.active_at("2026-10-02T06:09:59Z"), self.meaning["id"])
        self.assertEqual(self.desk.active_at("2026-10-02T06:10:00Z"), "compiled-v2")

    def test_public_availability_never_backdates_system_replay(self):
        for event in self.fixture["events"][:2]:
            self.desk.ingest(event)
        self.assertEqual(self.desk.visible_events("2026-10-02T06:30:03Z"), [])
        self.assertEqual([e["revision"] for e in self.desk.visible_events("2026-10-02T06:40:05Z")], [1])
        self.assertEqual([e["revision"] for e in self.desk.visible_events("2026-10-02T06:40:09Z")], [1, 2])

    def test_duplicate_receipt_does_not_overwrite_a_revision(self):
        event = self.fixture["events"][0]
        self.assertTrue(self.desk.ingest(event))
        self.assertFalse(self.desk.ingest(event))
        changed = copy.deepcopy(event)
        changed["facts"]["reported_measure"] = 99
        with self.assertRaises(ValueError):
            self.desk.ingest(changed)
        self.assertEqual(self.desk.visible_events(event["known_at"])[0]["facts"]["reported_measure"], 3.1)

    def test_known_at_cannot_precede_system_receipt(self):
        event = copy.deepcopy(self.fixture["events"][0])
        event["known_at"] = event["public_available_at"]
        with self.assertRaises(ValueError):
            self.desk.ingest(event)


class MaterialityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = load_fixture()

    def test_credible_severe_unknown_is_investigated_without_driver_match(self):
        decision = materiality(self.fixture["events"][2]["screening"])
        self.assertEqual(decision["route"], "investigate")
        self.assertTrue(decision["early_notice"])

    def test_novelty_alone_cannot_investigate_or_interrupt(self):
        decision = materiality(self.fixture["events"][3]["screening"])
        self.assertEqual(decision["route"], "audit_only")
        self.assertFalse(decision["early_notice"])

    def test_classifier_failure_and_unresolved_relevance_never_mean_low(self):
        screen = dict(self.fixture["events"][3]["screening"], classifier_available=False)
        self.assertEqual(materiality(screen)["route"], "unresolved_queue")
        screen.update(classifier_available=True, resolved=False)
        self.assertEqual(materiality(screen)["route"], "unresolved_queue")

    def test_trade_impact_can_escalate_without_thesis_impact(self):
        screen = dict(self.fixture["events"][3]["screening"], trade_impact=True)
        self.assertEqual(materiality(screen)["route"], "investigate")

    def test_distinct_developments_accumulate_and_offsets_reduce_signal(self):
        case = self.fixture["accumulation"]
        def at(cutoff):
            return accumulated(case["observations"], "real_yields", cutoff, case["window_seconds"], case["threshold"])
        self.assertFalse(at("2026-10-02T08:05:00Z")["material"])
        self.assertTrue(at("2026-10-02T08:15:00Z")["material"])
        result = at("2026-10-02T08:25:00Z")
        self.assertFalse(result["material"])
        self.assertEqual(len(result["event_ids"]), 3)
        self.assertFalse(at("2026-10-04T08:25:00Z")["material"])


class ReliabilityTests(DeskCase):
    def prepare_event(self):
        event = self.fixture["events"][0]
        self.desk.ingest(event)
        return event

    def publish(self, event, **kwargs):
        return self.desk.publish("assessment-v1", event, self.meaning["id"], event["known_at"], [{"field": "reported_measure", "value": 3.1}], **kwargs)

    def test_failure_rolls_back_both_assessment_and_notification(self):
        event = self.prepare_event()
        with self.assertRaises(RuntimeError):
            self.publish(event, fail_before_intent=True)
        self.assertEqual(self.desk.db.execute("SELECT count(*) FROM assessments").fetchone()[0], 0)
        self.assertEqual(self.desk.db.execute("SELECT count(*) FROM notification_intents").fetchone()[0], 0)
        self.publish(event)
        self.assertEqual(self.desk.db.execute("SELECT count(*) FROM notification_intents").fetchone()[0], 1)

    def test_retry_after_send_crash_reuses_delivery_identity(self):
        intent = self.publish(self.prepare_event())
        sink = set()
        with self.assertRaises(RuntimeError):
            self.desk.deliver(intent, sink, crash_after_send=True)
        self.assertTrue(self.desk.deliver(intent, sink))
        self.assertFalse(self.desk.deliver(intent, sink))
        self.assertEqual(sink, {intent})
        self.assertEqual(self.desk.db.execute("SELECT attempts FROM notification_intents").fetchone()[0], 2)

    def test_duplicate_analysis_does_not_create_another_intent(self):
        event = self.prepare_event()
        self.assertEqual(self.publish(event), self.publish(event))
        self.assertEqual(self.desk.db.execute("SELECT count(*) FROM notification_intents").fetchone()[0], 1)

    def test_correction_supersedes_pending_notice_and_rejects_old_analysis(self):
        original = self.prepare_event()
        intent = self.publish(original)
        correction = self.fixture["events"][1]
        self.desk.ingest(correction)
        self.assertFalse(self.desk.deliver(intent, set()))
        with self.assertRaises(ValueError):
            self.desk.publish("late-analysis", original, self.meaning["id"], correction["known_at"], [])
        self.assertEqual(self.desk.db.execute("SELECT is_current FROM assessments").fetchone()[0], 0)

    def test_old_interpretation_cannot_publish_after_new_approval(self):
        event = self.prepare_event()
        changed = dict(self.meaning, id="compiled-v2", horizon="one day")
        self.desk.approve(changed, self.thesis["owner_id"], "user", "2026-10-02T06:31:00Z", digest(self.thesis["text"]), digest(changed))
        with self.assertRaises(ValueError):
            self.desk.publish("late-meaning", event, self.meaning["id"], "2026-10-02T06:32:00Z", [])

    def test_wrong_source_field_value_cannot_be_published_as_fact(self):
        event = self.prepare_event()
        with self.assertRaises(ValueError):
            self.desk.publish("unsupported", event, self.meaning["id"], event["known_at"], [{"field": "reported_measure", "value": 9.9}])

    def test_new_approval_supersedes_existing_notice_and_current_assessment(self):
        event = self.prepare_event()
        intent = self.publish(event)
        changed = dict(self.meaning, id="compiled-v2", horizon="one day")
        self.desk.approve(changed, self.thesis["owner_id"], "user", "2026-10-02T06:31:00Z", digest(self.thesis["text"]), digest(changed))
        self.assertFalse(self.desk.deliver(intent, set()))
        self.assertEqual(self.desk.db.execute("SELECT is_current FROM assessments").fetchone()[0], 0)

    def test_publication_cannot_bypass_resolved_low_screening(self):
        event = self.fixture["events"][3]
        self.desk.ingest(event)
        with self.assertRaises(ValueError):
            self.desk.publish("noise", event, self.meaning["id"], event["known_at"], [])
        self.assertEqual(self.desk.db.execute("SELECT count(*) FROM notification_intents").fetchone()[0], 0)

    def test_backdated_publication_cannot_hide_a_received_correction(self):
        original = self.prepare_event()
        self.desk.ingest(self.fixture["events"][1])
        with self.assertRaises(ValueError):
            self.desk.publish("backdated", original, self.meaning["id"], original["known_at"], [])

    def test_material_brief_update_gets_new_intent_with_same_brief_identity(self):
        event = self.prepare_event()
        first_intent = self.publish(event)
        second_intent = self.desk.publish("material-update", event, self.meaning["id"], event["known_at"], [{"field": "reported_measure", "value": 3.1}], material_change=True)
        self.assertNotEqual(first_intent, second_intent)
        self.assertFalse(self.desk.deliver(first_intent, set()))
        payloads = [json.loads(row[0]) for row in self.desk.db.execute("SELECT payload FROM assessments")]
        self.assertEqual(payloads[0]["brief_id"], payloads[1]["brief_id"])
        self.assertTrue(self.desk.deliver(second_intent, set()))

    def test_nonmaterial_update_changes_history_without_new_interruption(self):
        event = self.prepare_event()
        first_intent = self.publish(event)
        self.assertIsNone(self.desk.publish("nonmaterial-update", event, self.meaning["id"], event["known_at"], [{"field": "reported_measure", "value": 3.1}], material_change=False))
        self.assertTrue(self.desk.deliver(first_intent, set()))
        self.assertEqual(self.desk.db.execute("SELECT count(*) FROM notification_intents").fetchone()[0], 1)

    def test_future_macro_context_cannot_enter_earlier_assessment(self):
        event = self.prepare_event()
        self.desk.context_versions["fixture-context-v1"]["known_at"] = "2026-10-03T06:00:00Z"
        with self.assertRaises(ValueError):
            self.publish(event)

    def test_notice_without_any_supported_fact_is_rejected(self):
        event = self.prepare_event()
        with self.assertRaises(ValueError):
            self.desk.publish("no-evidence", event, self.meaning["id"], event["known_at"], [])

    def test_source_use_contract_blocks_unauthorised_display(self):
        event = self.prepare_event()
        self.desk.context_versions[event["source_contract_version"]]["content"]["permitted_uses"] = ["capture"]
        with self.assertRaises(PermissionError):
            self.publish(event)


class FixtureTests(unittest.TestCase):
    def test_synthetic_schema_and_fixture_shape(self):
        schema = json.loads((ROOT / "contracts/pilot.schema.json").read_text())
        fixture = load_fixture()
        self.assertEqual(set(schema["required"]), set(fixture))
        self.assertTrue(fixture["synthetic"])
        self.assertEqual(fixture["schema_version"], schema["properties"]["schema_version"]["const"])
        for event in fixture["events"]:
            self.assertEqual(set(schema["$defs"]["event"]["required"]), set(event))
            self.assertEqual(set(schema["$defs"]["screening"]["required"]), set(event["screening"]))

    def test_same_inputs_reproduce_trace_without_model_calls(self):
        first, second = reference_trace(), reference_trace()
        self.assertEqual(first, second)
        self.assertEqual(first["provider_calls"], 0)
        self.assertEqual(first["provider_spend"], 0)
        self.assertTrue(first["synthetic"])


if __name__ == "__main__":
    unittest.main()
