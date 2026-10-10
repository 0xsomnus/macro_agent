"""Independent PostgreSQL scheduling, crash recovery and no-retry evidence."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from threading import Barrier
from unittest.mock import Mock
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, connections, transaction
from django.test import TransactionTestCase, override_settings

from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.monitoring.models import SourceState
from macro_agent.monitoring.analysis import model_configuration
from macro_agent.persistence.context_binding import book_digest
from macro_agent.positions.representation import exposure_book
from macro_agent.scheduling import service
from macro_agent.scheduling.configuration import configuration, scheduled_at
from macro_agent.scheduling.models import AnalysisDispatch, ScheduledSlot, SlotLease, SlotOutcome, WatchRecord, WatchVersion
from macro_agent.theses import service as theses


def independent(function):
    connections.close_all()
    try:
        return function()
    finally:
        connections.close_all()


@override_settings(SETTINGS_MODULE="macro_agent.web.local_settings", MACRO_ENABLE_MONITORING_PROOF=True,
                   MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ALLOW_SYNTHETIC_SETUP=True)
class PostgreSQLSchedulerTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            raise RuntimeError("Scheduler tests require PostgreSQL")
        self.at = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
        self.owner = get_user_model().objects.create_user(username="schedule-owner")
        self.other = get_user_model().objects.create_user(username="schedule-other")
        self.actor = str(self.owner.pk)
        contract = {"kind": "fictional_fixture", "label": "Scheduler-only fictional source"}
        self.source = SourceState.objects.create(pk="fixture-monitor", contract=contract,
                                                 contract_digest=text_digest(canonical_json(contract)))
        created = theses.create_thesis(self.actor, str(uuid4()), "Exact approved paper view.",
            {"drivers": ["Policy"], "horizon": "six weeks", "invalidation_signposts": []}, clock=lambda: self.at)
        draft = created["thesis"]["draft"]
        self.thesis_id = created["thesis"]["id"]
        approved = theses.approve_thesis(self.actor, self.thesis_id, str(uuid4()),
            draft["text_version"]["id"], draft["text_version"]["text_digest"],
            draft["interpretation"]["id"], draft["interpretation"]["digest"], created["thesis"]["revision"], clock=lambda: self.at)
        self.config = {"schema_version": "internal-desk-watch-v1",
            "approval_id": approved["thesis"]["approved"]["approval"]["id"],
            "exposure_digest": book_digest(exposure_book(self.thesis_id)),
            "sources": [{"source_id": "fixture-monitor", "contract_digest": self.source.contract_digest}],
            "provider": "nanogpt", "model_id": "Qwen/Qwen3-4B",
            "model_configuration": model_configuration("nanogpt"),
            "capture_interval_seconds": 60, "analysis_interval_seconds": 60, "lease_seconds": 30,
            "timezone": "UTC", "daily_time": "00:00", "daily_start_date": self.at.date().isoformat(),
            "daily_backlog_limit": 10,
            "context_bounds": {"reports": 100, "analyses": 1000, "exposure_versions": 200,
                               "issues": 100, "source_contracts": 16, "encoded_bytes": 262144},
            "allowances": {"window_seconds": 86400, "analysis_dispatches": 100, "inflight_slots": 1, "unresolved_slots": 1}}

    def watch(self, config=None):
        return service.configure_watch(self.actor, self.thesis_id, str(uuid4()), 0,
                                       config or self.config, clock=lambda: self.at)

    def enqueue(self, watch, *, at=None, kind=None):
        return service.enqueue_due(self.actor, watch["watch_id"], kind=kind, clock=lambda: at or self.at)

    def claim(self, kind, *, at=None, watch=None):
        return service.claim_due(self.actor, kind, watch_id=watch["watch_id"] if watch else None,
                                 clock=lambda: at or self.at)

    def request(self):
        return {"source_id": self.config["sources"][0]["source_id"],
            "expected_approval_id": self.config["approval_id"], "expected_exposure_digest": self.config["exposure_digest"],
            **{key: self.config[key] for key in ("provider", "model_id", "model_configuration")}}

    def guard(self, function):
        with self.assertRaises(DatabaseError) as error:
            with transaction.atomic():
                function()
        self.assertEqual(getattr(error.exception.__cause__, "sqlstate", None), "23514")

    def test_configuration_requires_explicit_safe_values_without_credentials(self):
        for key in self.config:
            changed = deepcopy(self.config)
            del changed[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.watch(changed)
        for key, value in (("capture_interval_seconds", True), ("timezone", "Missing/Zone"),
                           ("daily_time", "9:00"), ("daily_start_date", "20261009")):
            changed = {**self.config, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.watch(changed)
        changed = deepcopy(self.config)
        changed["model_configuration"]["api_key"] = "must-never-be-saved"
        with self.assertRaises(ValueError):
            self.watch(changed)
        self.assertFalse(WatchRecord.objects.exists())
        self.assertFalse(WatchVersion.objects.exists())

    def test_source_and_retained_analysis_implementation_caps_reject_overflow(self):
        changed = deepcopy(self.config)
        changed["sources"] = [{"source_id": f"source-{index}", "contract_digest": "c" * 64} for index in range(17)]
        with self.assertRaises(ValueError):
            self.watch(changed)
        changed = deepcopy(self.config)
        changed["context_bounds"]["analyses"] = 1001
        with self.assertRaises(ValueError):
            self.watch(changed)

    def test_configure_pins_current_approval_and_complete_exposure(self):
        for key, value in (("approval_id", str(uuid4())), ("exposure_digest", "f" * 64)):
            with self.subTest(key=key), self.assertRaises(service.ScheduleConflict):
                self.watch({**self.config, key: value})
        self.assertFalse(WatchVersion.objects.exists())

    def test_configuration_rejects_missing_changed_or_unpermitted_source_contracts(self):
        for entry in ({"source_id": "missing", "contract_digest": self.source.contract_digest},
                      {"source_id": self.source.pk, "contract_digest": "f" * 64}):
            with self.subTest(entry=entry), self.assertRaises(service.ScheduleUnavailable):
                self.watch({**self.config, "sources": [entry]})
        with override_settings(MACRO_ALLOW_SYNTHETIC_SETUP=False, SETTINGS_MODULE="macro_agent.web.local_settings"), self.assertRaises(service.ScheduleUnavailable):
            self.watch()
        self.assertFalse(WatchVersion.objects.exists())

    def test_duplicate_configuration_and_later_replay_do_not_reactivate_old_version(self):
        command = str(uuid4())
        first = service.configure_watch(self.actor, self.thesis_id, command, 0, self.config, clock=lambda: self.at)
        changed = {**self.config, "capture_interval_seconds": 90}
        current = service.configure_watch(self.actor, self.thesis_id, str(uuid4()), 1, changed,
                                           clock=lambda: self.at + timedelta(seconds=1))
        replay = service.configure_watch(self.actor, self.thesis_id, command, 0, self.config,
                                         clock=lambda: self.at + timedelta(seconds=2))
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["watch_version_id"], current["watch_version_id"])
        self.assertEqual(replay["original_watch_version_id"], first["watch_version_id"])
        self.assertEqual(WatchVersion.objects.count(), 2)

    def test_periodic_coalescing_retains_old_intention_without_fake_coverage(self):
        watch = self.watch()
        output = self.enqueue(watch, at=self.at + timedelta(seconds=180), kind="capture")
        self.assertEqual(len(output["slots"]), 1)
        slot = output["slots"][0]
        self.assertEqual(slot["intended_at"], self.at.isoformat())
        self.assertEqual(slot["coalesced_intervals"], 3)
        self.assertTrue(slot["late"])
        self.assertEqual(self.enqueue(watch, at=self.at + timedelta(seconds=180), kind="capture")["slots"], [])
        self.assertEqual(service.inspect_watch(self.actor, watch["watch_id"])["next_capture_at"],
                         (self.at + timedelta(seconds=240)).isoformat())

    def test_missed_daily_dates_create_once_after_restart_and_remain_labelled_late(self):
        config = {**self.config, "daily_start_date": "2026-10-07"}
        watch = self.watch(config)
        with ThreadPoolExecutor(max_workers=1) as pool:
            output = pool.submit(independent, lambda: self.enqueue(watch, kind="daily_review")).result(timeout=10)
        self.assertEqual([item["local_date"] for item in output["slots"]], ["2026-10-07", "2026-10-08", "2026-10-09"])
        self.assertTrue(all(item["late"] and item["coalesced_intervals"] == 0 for item in output["slots"]))
        self.assertEqual(output["slots"][1]["period_start"], output["slots"][0]["cutoff"])
        revised = {**config, "daily_time": "01:00"}
        service.configure_watch(self.actor, self.thesis_id, str(uuid4()), 1, revised,
                                 clock=lambda: self.at + timedelta(seconds=1))
        self.assertEqual(self.enqueue(watch, at=self.at + timedelta(seconds=2), kind="daily_review")["slots"], [])
        self.assertEqual(ScheduledSlot.objects.filter(kind="daily_review").count(), 3)

    def test_daily_backlog_overflow_is_visible_without_blocking_capture_or_skipping_dates(self):
        watch = self.watch({**self.config, "daily_start_date": "2026-10-01", "daily_backlog_limit": 2})
        output = self.enqueue(watch)
        self.assertEqual(output["daily_backlog"]["status"], "overflow")
        self.assertEqual(output["daily_backlog"]["due_dates"], 9)
        self.assertFalse(ScheduledSlot.objects.filter(kind="daily_review").exists())
        self.assertTrue(ScheduledSlot.objects.filter(kind="capture").exists())
        self.assertEqual(WatchRecord.objects.get().next_daily_date, date(2026, 10, 1))

    def test_independent_duplicate_ticks_create_one_slot_per_kind_and_date(self):
        watch = self.watch()
        ready = Barrier(2)
        def tick():
            ready.wait(timeout=5)
            return self.enqueue(watch)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [item.result(timeout=15) for item in [pool.submit(independent, tick), pool.submit(independent, tick)]]
        self.assertEqual(sum(len(item["slots"]) for item in results), 3)
        self.assertEqual(ScheduledSlot.objects.count(), 3)

    def test_independent_competing_claims_admit_one_active_lease(self):
        watch = self.watch()
        self.enqueue(watch, kind="capture")
        ready = Barrier(2)
        def claim():
            ready.wait(timeout=5)
            return self.claim("capture")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [item.result(timeout=15) for item in [pool.submit(independent, claim), pool.submit(independent, claim)]]
        self.assertEqual(sum(item is not None for item in results), 1)
        self.assertEqual(SlotLease.objects.count(), 1)

    def test_restart_recovers_unstarted_work_with_same_command_and_fences_old_token(self):
        watch = self.watch()
        self.enqueue(watch, kind="analysis")
        first = self.claim("analysis")
        with ThreadPoolExecutor(max_workers=1) as pool:
            recovered = pool.submit(independent, lambda: self.claim("analysis", at=self.at + timedelta(seconds=31))).result(timeout=10)
        self.assertEqual(first["command_id"], recovered["command_id"])
        self.assertEqual(recovered["mode"], "execute")
        self.assertEqual(SlotOutcome.objects.get().status, "expired")
        with self.assertRaises(service.ScheduleFenced):
            service.complete_slot(self.actor, first["token"], "completed", {}, clock=lambda: self.at + timedelta(seconds=32))

    def test_started_analysis_restart_can_only_recover_saved_request_without_paid_retry(self):
        watch = self.watch()
        self.enqueue(watch, kind="analysis")
        first = self.claim("analysis")
        service.mark_analysis_started(self.actor, first["token"], self.request(), clock=lambda: self.at)
        with self.assertRaises(service.InferenceAlreadyStarted):
            service.mark_analysis_started(self.actor, first["token"], self.request(), clock=lambda: self.at)
        with ThreadPoolExecutor(max_workers=1) as pool:
            recovered = pool.submit(independent, lambda: self.claim("analysis", at=self.at + timedelta(seconds=31))).result(timeout=10)
        self.assertEqual(recovered["mode"], "recover")
        self.assertEqual(recovered["analysis_request"], self.request())
        self.assertEqual(recovered["command_id"], first["command_id"])
        self.assertEqual(AnalysisDispatch.objects.count(), 1)
        with self.assertRaises(service.InferenceAlreadyStarted):
            service.mark_analysis_started(self.actor, recovered["token"], self.request(), clock=lambda: self.at + timedelta(seconds=31))

    def test_oldest_daily_lease_and_failure_bar_newer_daily_contexts(self):
        watch = self.watch({**self.config, "daily_start_date": "2026-10-08"})
        self.enqueue(watch)
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(independent, lambda: self.claim("daily_review")).result(timeout=10)
        self.assertEqual(first["local_date"], "2026-10-08")
        self.assertIsNone(self.claim("daily_review"))
        service.complete_slot(self.actor, first["token"], "blocked", {"reason": "context_overflow"}, clock=lambda: self.at)
        with ThreadPoolExecutor(max_workers=1) as pool:
            self.assertIsNone(pool.submit(independent, lambda: self.claim("daily_review")).result(timeout=10))
        self.assertIsNotNone(self.claim("capture"))
        self.assertIsNotNone(self.claim("analysis"))

    def test_successful_daily_completion_unlocks_exact_next_interval(self):
        watch = self.watch({**self.config, "daily_start_date": "2026-10-08"})
        self.enqueue(watch, kind="daily_review")
        first = self.claim("daily_review")
        service.complete_slot(self.actor, first["token"], "completed", {"review_id": "persisted-reference"}, clock=lambda: self.at)
        second = self.claim("daily_review")
        self.assertEqual(second["period_start"], first["cutoff"])
        self.assertEqual(second["local_date"], "2026-10-09")

    def test_unknown_analysis_blocks_new_paid_dispatch_but_capture_and_daily_continue(self):
        watch = self.watch()
        self.enqueue(watch)
        first = self.claim("analysis")
        service.mark_analysis_started(self.actor, first["token"], self.request(), clock=lambda: self.at)
        service.complete_slot(self.actor, first["token"], "unresolved", {"remote_outcome": "unknown"}, clock=lambda: self.at)
        self.enqueue(watch, at=self.at + timedelta(seconds=61), kind="analysis")
        second = self.claim("analysis", at=self.at + timedelta(seconds=61))
        with self.assertRaises(service.ScheduleConflict):
            service.mark_analysis_started(self.actor, second["token"], self.request(), clock=lambda: self.at + timedelta(seconds=61))
        self.assertIsNotNone(self.claim("capture", at=self.at + timedelta(seconds=61)))
        self.assertIsNotNone(self.claim("daily_review", at=self.at + timedelta(seconds=61)))
        self.assertEqual(AnalysisDispatch.objects.count(), 1)

    def test_expired_dispatch_counts_as_unknown_even_before_read_only_recovery(self):
        config = deepcopy(self.config)
        config["allowances"]["inflight_slots"] = 2
        watch = self.watch(config)
        self.enqueue(watch, kind="analysis")
        first = self.claim("analysis")
        service.mark_analysis_started(self.actor, first["token"], self.request(), clock=lambda: self.at)
        self.enqueue(watch, at=self.at + timedelta(seconds=61), kind="analysis")
        recovered = self.claim("analysis", at=self.at + timedelta(seconds=61))
        self.assertEqual(recovered["mode"], "recover")
        fresh = self.claim("analysis", at=self.at + timedelta(seconds=61))
        with self.assertRaises(service.ScheduleConflict):
            service.mark_analysis_started(self.actor, fresh["token"], self.request(), clock=lambda: self.at + timedelta(seconds=61))

    def test_no_dispatch_preflight_failure_does_not_consume_unknown_paid_allowance(self):
        watch = self.watch()
        self.enqueue(watch, kind="analysis")
        blocked = self.claim("analysis")
        service.complete_slot(self.actor, blocked["token"], "blocked", {"reason": "missing_model_key"}, clock=lambda: self.at)
        self.enqueue(watch, at=self.at + timedelta(seconds=61), kind="analysis")
        fresh = self.claim("analysis", at=self.at + timedelta(seconds=61))
        marker = service.mark_analysis_started(self.actor, fresh["token"], self.request(), clock=lambda: self.at + timedelta(seconds=61))
        self.assertEqual(marker["mode"], "execute")
        self.assertEqual(AnalysisDispatch.objects.count(), 1)

    def test_pin_or_request_change_blocks_dispatch_before_any_paid_boundary(self):
        watch = self.watch()
        self.enqueue(watch, kind="analysis")
        lease = self.claim("analysis")
        for key, value in (("expected_approval_id", str(uuid4())), ("source_id", "unselected"), ("model_id", "different/model")):
            with self.subTest(key=key), self.assertRaises(service.ScheduleConflict):
                service.mark_analysis_started(self.actor, lease["token"], {**self.request(), key: value}, clock=lambda: self.at)
        self.assertFalse(AnalysisDispatch.objects.exists())

    def test_owner_scope_and_locked_owner_are_opaque_and_clock_is_sampled_after_protection(self):
        watch = self.watch()
        self.enqueue(watch, kind="capture")
        with self.assertRaises(service.ScheduleUnavailable):
            service.inspect_watch(str(self.other.pk), watch["watch_id"])
        self.assertIsNone(service.claim_due(str(self.other.pk), "capture", watch_id=watch["watch_id"]))
        clock = Mock(side_effect=AssertionError("Clock must not run before locked owner is available"))
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=self.owner.pk)
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertIsNone(pool.submit(independent, lambda: service.claim_due(self.actor, "capture", clock=clock)).result(timeout=10))
        clock.assert_not_called()

    def test_clock_rollback_naive_clock_and_caller_transactions_do_not_mutate_state(self):
        watch = self.watch()
        for at in (self.at - timedelta(seconds=1), self.at.replace(tzinfo=None)):
            with self.subTest(at=at), self.assertRaises(ValueError):
                self.enqueue(watch, at=at)
        self.assertFalse(ScheduledSlot.objects.exists())
        with transaction.atomic(), self.assertRaises(RuntimeError):
            self.enqueue(watch)
        original = connection.get_autocommit()
        try:
            connection.set_autocommit(False)
            with self.assertRaises(RuntimeError):
                self.enqueue(watch)
        finally:
            connection.rollback()
            connection.set_autocommit(original)

    def test_database_guards_preserve_identity_scope_and_immutable_history(self):
        watch = self.watch()
        self.enqueue(watch, kind="analysis")
        lease = self.claim("analysis")
        service.mark_analysis_started(self.actor, lease["token"], self.request(), clock=lambda: self.at)
        service.complete_slot(self.actor, lease["token"], "completed", {"saved": True}, clock=lambda: self.at)
        for model, values in ((WatchVersion, {"configuration": {}}), (SlotLease, {"mode": "recover"}),
                              (SlotOutcome, {"payload": {}}), (AnalysisDispatch, {"request": {}}),
                              (ScheduledSlot, {"state": "pending", "active_token": None, "lease_until": None})):
            with self.subTest(model=model.__name__):
                self.guard(lambda model=model, values=values: model.objects.all().update(**values))
        self.guard(lambda: WatchRecord.objects.all().update(owner_id=self.other.pk))
        row = ScheduledSlot.objects.get()
        self.guard(lambda: ScheduledSlot.objects.create(owner=self.other, thesis_id=self.thesis_id,
            watch_id=watch["watch_id"], watch_version_id=watch["watch_version_id"], kind="capture",
            identity_key="forged", intended_at=self.at, created_at=self.at, late=False))
        self.assertEqual(row.command_id, ScheduledSlot.objects.get().command_id)

    def test_read_only_inspection_does_not_expire_started_work_or_infer(self):
        watch = self.watch()
        self.enqueue(watch, kind="analysis")
        lease = self.claim("analysis")
        service.mark_analysis_started(self.actor, lease["token"], self.request(), clock=lambda: self.at)
        before = (SlotLease.objects.count(), SlotOutcome.objects.count(), AnalysisDispatch.objects.count())
        with ThreadPoolExecutor(max_workers=1) as pool:
            output = pool.submit(independent, lambda: service.inspect_watch(self.actor, watch["watch_id"])).result(timeout=10)
        self.assertEqual(output["configuration"], self.config)
        self.assertEqual(output["slots"][0]["analysis_request"], self.request())
        self.assertEqual(before, (SlotLease.objects.count(), SlotOutcome.objects.count(), AnalysisDispatch.objects.count()))

    def test_current_watch_does_not_scan_slot_or_lease_history(self):
        watch = self.watch()
        self.enqueue(watch)
        observed = []
        def queries(execute, sql, params, many, context):
            observed.append(sql)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(queries):
            current = service.current_watch(self.actor, watch["watch_id"])
        self.assertEqual(current["configuration"], self.config)
        self.assertFalse(any("macro_scheduling_scheduledslot" in sql or "macro_scheduling_slotlease" in sql for sql in observed))

    def test_dst_gap_and_ambiguity_require_explicit_schedule_repair(self):
        config = {**self.config, "timezone": "America/New_York", "daily_time": "02:30"}
        with self.assertRaisesRegex(ValueError, "does not exist"):
            scheduled_at(date(2026, 3, 8), config)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            scheduled_at(date(2026, 11, 1), {**config, "daily_time": "01:30"})
