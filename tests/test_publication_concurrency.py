"""Real file-backed SQLite interleavings for the test-only persistence port.

These tests prove the lab adapter protocol. They do not certify a production
database, external delivery, or live source coverage.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from threading import Event
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from domain_fixture import correction_pin, fixture_case
from lab_sqlite_store import SQLitePublicationStore
from macro_agent.application.publication import publish


class _PausedReadStore:
    """Pause immediately after a real protected state read, before publication."""

    def __init__(self, store, read, release):
        self.store, self.read, self.release = store, read, release

    @contextmanager
    def transaction(self, brief_id):
        with self.store.transaction(brief_id) as transaction:
            read, release = self.read, self.release

            class PausedTransaction:
                def state(self):
                    state = transaction.state()
                    read.set()
                    if not release.wait(10):
                        raise TimeoutError("protected publication read was not released")
                    return state

                def existing(self, assessment_id):
                    return transaction.existing(assessment_id)

                def save(self, candidate, decision, at):
                    transaction.save(candidate, decision, at)

            yield PausedTransaction()


class SQLitePublicationConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "ordering.sqlite"
        self.store = SQLitePublicationStore(self.path)
        self.candidate, dependencies = fixture_case()
        self.initial_at = self.candidate.snapshot.cutoff
        self.correction = correction_pin()
        self.store.bootstrap(self.candidate.brief_id, self.candidate.owner_id,
                             dependencies, self.initial_at)

    def report(self):
        return self.store.inspect(self.candidate.brief_id)

    def test_correction_commits_before_old_analysis_publishes(self):
        analysis_started, corrected = Event(), Event()
        correction_store = SQLitePublicationStore(self.path)

        def analyze_then_publish():
            # The immutable r1 snapshot is captured before the correction.
            analysis_started.set()
            if not corrected.wait(10):
                raise TimeoutError("correction did not commit")
            return publish(self.store, self.candidate, self.correction.known_at + timedelta(seconds=1))

        def correct():
            if not analysis_started.wait(10):
                raise TimeoutError("analysis did not start")
            correction_store.advance_dependency(self.candidate.brief_id, self.correction,
                                                self.correction.known_at)
            corrected.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            old_analysis = executor.submit(analyze_then_publish)
            correction = executor.submit(correct)
            correction.result(timeout=15)
            decision = old_analysis.result(timeout=15)
        self.assertEqual(decision.status, "superseded")
        self.assertIn("changed:event_revision", decision.reasons)
        report = self.report()
        self.assertIsNone(report["current_assessment_id"])
        self.assertEqual(report["generation"], 0)
        self.assertEqual(len(report["assessments"]), 1)
        self.assertEqual(report["notifications"], [])
        self.assertEqual(len(report["reassessment"]), 1)
        self.assertEqual(report["reassessment"][0]["state"], "pending")
        self.assertEqual(report["assessments"][0]["payload"]["assessment_id"], self.candidate.assessment_id)
        fresh, _ = fixture_case("analysis-r2", revision=2)
        self.assertEqual(publish(self.store, fresh, self.correction.known_at + timedelta(seconds=2)).status,
                         "current")
        self.assertEqual(self.report()["reassessment"][0]["state"], "completed")

    def test_protected_read_orders_publication_before_correction(self):
        protected_read, release_publication = Event(), Event()
        blocked_writer, correction_committed = Event(), Event()
        correction_store = SQLitePublicationStore(self.path)
        paused_store = _PausedReadStore(self.store, protected_read, release_publication)

        def correct_on_separate_connection():
            # An immediate independent lock attempt proves that the transaction
            # has a write reservation, rather than relying on thread timing.
            connection = sqlite3.connect(self.path, timeout=0, isolation_level=None)
            try:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as error:
                    if "locked" not in str(error):
                        raise
                    blocked_writer.set()
                else:
                    connection.rollback()
                    raise AssertionError("correction acquired lock during protected read")
            finally:
                connection.close()
            correction_store.advance_dependency(self.candidate.brief_id, self.correction,
                                                self.correction.known_at)
            correction_committed.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            publication = executor.submit(publish, paused_store, self.candidate,
                                          self.initial_at + timedelta(seconds=1))
            try:
                self.assertTrue(protected_read.wait(10), "publisher never reached protected read")
                correction = executor.submit(correct_on_separate_connection)
                self.assertTrue(blocked_writer.wait(10), "separate connection was not blocked")
                self.assertFalse(correction_committed.is_set())
            finally:
                release_publication.set()
            self.assertEqual(publication.result(timeout=15).status, "current")
            correction.result(timeout=15)
        report = self.report()
        self.assertIsNone(report["current_assessment_id"])
        self.assertEqual(report["generation"], 1)
        self.assertEqual(report["assessments"][0]["decision"]["status"], "current")
        self.assertFalse(report["assessments"][0]["is_current"])
        self.assertEqual(report["notifications"][0]["state"], "canceled")
        self.assertEqual([entry["kind"] for entry in report["audit"]],
                         ["bootstrap", "publication", "dependency_advanced"])

    def test_runtime_clock_is_sampled_after_waiting_for_committed_correction(self):
        correction_written, release_commit = Event(), Event()
        publication_attempted, protected_read, clock_called = Event(), Event(), Event()
        no_read_pause = Event()
        no_read_pause.set()
        fake_now = [self.initial_at]

        class HeldCorrectionStore(SQLitePublicationStore):
            @contextmanager
            def _write(self):
                with super()._write() as connection:
                    yield connection
                    correction_written.set()
                    if not release_commit.wait(10):
                        raise TimeoutError("correction commit was not released")

        class ObservedPublicationStore(SQLitePublicationStore):
            @contextmanager
            def _connection(self, *, readonly=False):
                with super()._connection(readonly=readonly) as connection:
                    if not readonly:
                        connection.set_trace_callback(
                            lambda sql: publication_attempted.set() if sql == "BEGIN IMMEDIATE" else None)
                    yield connection

        correction_store = HeldCorrectionStore(self.path)
        publication_store = _PausedReadStore(ObservedPublicationStore(self.path),
                                             protected_read, no_read_pause)

        def clock():
            self.assertTrue(protected_read.is_set(), "clock ran before protected state read")
            clock_called.set()
            return fake_now[0]

        with ThreadPoolExecutor(max_workers=2) as executor:
            correction = executor.submit(correction_store.advance_dependency,
                                         self.candidate.brief_id, self.correction, self.correction.known_at)
            try:
                self.assertTrue(correction_written.wait(10), "correction never reached pre-commit barrier")
                publication = executor.submit(publish, publication_store, self.candidate, clock)
                self.assertTrue(publication_attempted.wait(10), "publisher never attempted its write reservation")
                self.assertFalse(protected_read.is_set())
                self.assertFalse(clock_called.is_set())
                # The caller's old timestamp is now obsolete. The runtime clock
                # changes while publication is blocked behind the correction.
                fake_now[0] = self.correction.known_at + timedelta(seconds=1)
            finally:
                release_commit.set()
            correction.result(timeout=15)
            self.assertEqual(publication.result(timeout=15).status, "superseded")
        report = self.report()
        self.assertTrue(clock_called.is_set())
        self.assertEqual(report["assessments"][0]["saved_at"], fake_now[0].isoformat())
        self.assertEqual(report["notifications"], [])
        self.assertEqual([entry["kind"] for entry in report["audit"]],
                         ["bootstrap", "dependency_advanced", "publication"])

    def test_generation_rejects_late_run_using_unchanged_context(self):
        publish(self.store, self.candidate, self.initial_at + timedelta(seconds=1))
        late, _ = fixture_case("late-same-context", expected_generation=0)
        result = publish(self.store, late, self.initial_at + timedelta(seconds=2))
        self.assertEqual((result.status, result.reasons, result.reassessment_required),
                         ("superseded", ("newer_publication",), False))
        report = self.report()
        self.assertEqual(report["current_assessment_id"], self.candidate.assessment_id)
        self.assertEqual(report["generation"], 1)
        self.assertEqual(len(report["notifications"]), 1)
        self.assertEqual(report["reassessment"], [])

    def test_retry_is_idempotent_and_correction_cannot_be_undone(self):
        publish(self.store, self.candidate, self.initial_at + timedelta(seconds=1))
        before = self.report()
        self.assertEqual(publish(self.store, self.candidate, self.initial_at + timedelta(seconds=2)).status,
                         "current")
        self.assertEqual(self.report(), before)
        self.store.advance_dependency(self.candidate.brief_id, self.correction, self.correction.known_at)
        corrected = self.report()
        self.assertEqual(publish(self.store, self.candidate, self.correction.known_at + timedelta(seconds=1)).status,
                         "superseded")
        self.assertEqual(self.report(), corrected)
        self.assertFalse(self.store.mark_delivered(self.candidate.intent_id,
                                                  self.correction.known_at + timedelta(seconds=2)))

    def test_failure_rolls_back_assessment_pointer_history_intent_and_audit(self):
        publish(self.store, self.candidate, self.initial_at + timedelta(seconds=1))
        next_candidate, _ = fixture_case("material-update", expected_generation=1)
        before = self.report()
        self.store.fail_before_intent = True
        with self.assertRaisesRegex(RuntimeError, "injected failure"):
            publish(self.store, next_candidate, self.initial_at + timedelta(seconds=2))
        self.assertEqual(self.report(), before)
        self.store.fail_before_intent = False
        publish(self.store, next_candidate, self.initial_at + timedelta(seconds=3))
        states = {row["assessment_id"]: row["state"] for row in self.report()["notifications"]}
        self.assertEqual(states, {self.candidate.assessment_id: "canceled", next_candidate.assessment_id: "pending"})

    def test_nonmaterial_publication_keeps_valid_older_material_notice(self):
        publish(self.store, self.candidate, self.initial_at + timedelta(seconds=1))
        update, _ = fixture_case("nonmaterial-update", expected_generation=1)
        update = replace(update, material_change=False)
        publish(self.store, update, self.initial_at + timedelta(seconds=2))
        report = self.report()
        self.assertEqual(report["current_assessment_id"], update.assessment_id)
        self.assertEqual(len(report["notifications"]), 1)
        self.assertEqual(report["notifications"][0]["state"], "pending")
        # A retry reports current disposition and cannot revive an older pointer,
        # even though its still-valid pending material notice is retained.
        self.assertEqual(publish(self.store, self.candidate,
                                 self.initial_at + timedelta(seconds=3)).status, "superseded")
        self.assertEqual(self.report(), report)
        self.assertTrue(self.store.mark_delivered(self.candidate.intent_id,
                                                 self.initial_at + timedelta(seconds=3)))
        self.assertFalse(self.store.mark_delivered(self.candidate.intent_id,
                                                  self.initial_at + timedelta(seconds=4)))

    def test_correction_invalidates_notice_from_before_nonmaterial_update(self):
        publish(self.store, self.candidate, self.initial_at + timedelta(seconds=1))
        update, _ = fixture_case("nonmaterial-update", expected_generation=1)
        publish(self.store, replace(update, material_change=False), self.initial_at + timedelta(seconds=2))
        self.store.advance_dependency(self.candidate.brief_id, self.correction, self.correction.known_at)
        report = self.report()
        self.assertIsNone(report["current_assessment_id"])
        self.assertEqual(report["notifications"][0]["state"], "canceled")
        self.assertEqual(len(report["reassessment"]), 1)

    def test_any_governing_dependency_change_invalidates_currentness(self):
        publish(self.store, self.candidate, self.initial_at + timedelta(seconds=1))
        exposure = self.candidate.snapshot.dependency("exposure")
        changed = replace(exposure, version_id="exposure-v2", digest="2" * 64,
                          known_at=self.initial_at + timedelta(seconds=2))
        self.store.advance_dependency(self.candidate.brief_id, changed, changed.known_at)
        report = self.report()
        self.assertIsNone(report["current_assessment_id"])
        self.assertEqual(report["notifications"][0]["state"], "canceled")
        self.assertEqual(report["reassessment"][0]["reason"], "changed:exposure")

    def test_version_identity_and_times_are_immutable(self):
        original = self.candidate.snapshot.dependency("event_revision")
        before = self.report()
        for changed in (replace(original, digest="0" * 64),
                        replace(original, known_at=original.known_at + timedelta(seconds=1))):
            with self.subTest(pin=changed):
                with self.assertRaisesRegex(ValueError, "cannot change"):
                    self.store.advance_dependency(self.candidate.brief_id, changed,
                                                  self.initial_at + timedelta(seconds=2))
                self.assertEqual(self.report(), before)
        backwards = replace(original, version_id="old-arrival", known_at=original.known_at - timedelta(seconds=1))
        with self.assertRaisesRegex(ValueError, "backwards"):
            self.store.advance_dependency(self.candidate.brief_id, backwards, self.initial_at)
        with self.assertRaisesRegex(ValueError, "backdated"):
            self.store.advance_dependency(self.candidate.brief_id, self.correction, self.initial_at)
        self.assertEqual(self.report(), before)

    def test_equal_time_old_head_cannot_be_restored(self):
        original = self.candidate.snapshot.dependency("event_revision")
        replacement = replace(original, version_id="equal-time-correction", digest="e" * 64)
        self.store.advance_dependency(self.candidate.brief_id, replacement,
                                      self.initial_at + timedelta(seconds=1))
        activated = self.report()
        self.store.advance_dependency(self.candidate.brief_id, replacement,
                                      self.initial_at + timedelta(seconds=2))
        self.assertEqual(self.report(), activated)
        self.assertEqual(publish(self.store, self.candidate,
                                 self.initial_at + timedelta(seconds=3)).status, "superseded")
        before_restore = self.report()
        with self.assertRaisesRegex(ValueError, "previously activated"):
            self.store.advance_dependency(self.candidate.brief_id, original,
                                          self.initial_at + timedelta(seconds=4))
        self.assertEqual(self.report(), before_restore)
        self.assertEqual(publish(self.store, self.candidate,
                                 self.initial_at + timedelta(seconds=5)).status, "superseded")
        self.assertEqual(self.report(), before_restore)
        self.assertIsNone(before_restore["current_assessment_id"])
        self.assertEqual(before_restore["notifications"], [])

    def test_identity_scopes_and_owner_boundary(self):
        publish(self.store, self.candidate, self.initial_at + timedelta(seconds=1))
        before = self.report()
        with self.assertRaises(PermissionError):
            publish(self.store, replace(self.candidate, owner_id="foreign-owner"),
                    self.initial_at + timedelta(seconds=2))
        with self.assertRaisesRegex(ValueError, "identity reused"):
            publish(self.store, replace(self.candidate, run_id="different-run"),
                    self.initial_at + timedelta(seconds=2))
        self.assertEqual(self.report(), before)
        other = replace(self.candidate, brief_id="other-brief", owner_id="other-owner")
        self.store.bootstrap(other.brief_id, other.owner_id, other.snapshot.dependencies, self.initial_at)
        self.assertEqual(publish(self.store, other, self.initial_at + timedelta(seconds=1)).status, "current")
        self.assertNotEqual(self.candidate.intent_id, other.intent_id)
        self.assertEqual(len(self.store.inspect(other.brief_id)["notifications"]), 1)

    def test_audit_and_history_are_append_only_and_inspection_is_read_only(self):
        publish(self.store, self.candidate, self.initial_at + timedelta(seconds=1))
        before = self.report()
        self.assertEqual(self.report(), before)
        with sqlite3.connect(self.path) as connection:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable history"):
                connection.execute("UPDATE audit SET kind = 'tampered'")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable history"):
                connection.execute("DELETE FROM assessments")
        self.assertEqual(self.report(), before)


if __name__ == "__main__":
    unittest.main()
