"""Independent connections challenge the shared cap and immutable money history."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as dt_timezone
from threading import Barrier, Event
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings

from macro_agent.desk import search_budget as ledger
from macro_agent.desk.investigation import BOUNDS
from macro_agent.desk.investigation_models import ResearchRun
from macro_agent.desk.search_budget_models import (
    SearchBudgetRoot, SearchPriceContract, SearchReservation, SearchSettlement,
)
from macro_agent.domain.models import canonical_json, text_digest
from macro_agent.theses import service
from macro_agent.theses.models import ThesisRecord


class Clock:
    def __init__(self):
        self.at = datetime(2026, 10, 21, 9, tzinfo=dt_timezone.utc)

    def __call__(self):
        return self.at


@override_settings(MACRO_ENABLE_CONTINUOUS_DESK=True, MACRO_ENABLE_MONITORING_PROOF=True,
    MACRO_ALLOW_SYNTHETIC_SETUP=True, SETTINGS_MODULE="macro_agent.web.local_settings")
class SearchBudgetTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="search-budget-owner")
        self.other = get_user_model().objects.create_user(username="search-budget-other", is_staff=True)
        self.operator = get_user_model().objects.create_user(username="search-budget-operator", is_staff=True)
        self.actor, self.staff = str(self.owner.pk), str(self.operator.pk)
        self.clock = Clock()
        self.run = self.make_run()
        self.price = self.make_price(10_000)

    def make_run(self, owner=None):
        actor = str((owner or self.owner).pk)
        value = service.create_thesis(actor, str(uuid4()), "Explore a recorded commodity question",
            {"drivers": [], "horizon": None, "invalidation_signposts": []}, clock=self.clock)
        thesis = ThesisRecord.objects.get(pk=value["thesis"]["id"])
        return ResearchRun.objects.create(owner_id=actor, command_id=uuid4(), request_digest="a" * 64,
            exact_question=thesis.latest_text.exact_text, thesis=thesis, initial_text=thesis.latest_text,
            initial_revision=thesis.revision, provider="nanogpt", model_id="recorded/research",
            bounds=BOUNDS, created_at=self.clock())

    def price_document(self, amount, provider="recorded_search"):
        return {"schema_version": ledger.PRICE_SCHEMA, "provider_id": provider, "currency": "USD",
            "billing_basis": "per_request_upper_bound", "maximum_charge_microusd": amount,
            "pricing_reference": "Recorded fixture price, not a live provider plan",
            "pricing_evidence_digest": "b" * 64}

    def make_price(self, amount, provider="recorded_search"):
        return ledger.record_price_contract(self.staff, self.price_document(amount, provider), clock=self.clock)

    def reserve(self, run=None, price=None, call=None, actor=None):
        return ledger.reserve_search(actor or self.actor, str((run or self.run).pk),
            call or str(uuid4()), (price or self.price).pk, clock=self.clock)

    def evidence(self, amount):
        return {"kind": "provider_zero_charge_confirmation" if amount == 0 else "provider_charge_record",
                "reference": "Recorded final provider charge evidence", "evidence_digest": "c" * 64}

    def settle(self, booking, charge):
        return ledger.settle_search(self.staff, booking["call_id"], charge, self.evidence(charge), clock=self.clock)

    def test_saved_call_remains_read_only_after_restart_month_and_input_change(self):
        call = str(uuid4())
        saved = self.reserve(call=call)
        self.clock.at = datetime(2026, 11, 1, tzinfo=dt_timezone.utc)
        current = service.get_thesis(self.actor, str(self.run.thesis_id))
        service.propose_thesis(self.actor, str(self.run.thesis_id), str(uuid4()),
            "Changed research input", {"drivers": [], "horizon": None,
            "invalidation_signposts": []}, current["revision"], clock=self.clock)
        with patch.object(ledger, "_price", side_effect=AssertionError("No pricing eligibility replay")):
            replay = self.reserve(call=call)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["month_start"], saved["month_start"])
        self.assertEqual(SearchReservation.objects.count(), 1)
        self.assertEqual(replay["held_microusd"], 10_000)
        self.assertIsNone(replay["actual_charge_microusd"])

    def test_unknown_holds_full_amount_across_months_and_providers(self):
        self.reserve(price=self.make_price(90_000))
        self.clock.at = datetime(2026, 11, 1, tzinfo=dt_timezone.utc)
        self.reserve(price=self.make_price(10_000, "another_recorded_source"))
        with self.assertRaises(ledger.SearchBudgetExhausted):
            self.reserve(price=self.make_price(1))
        self.assertEqual(SearchReservation.objects.count(), 2)
        self.assertEqual(SearchSettlement.objects.count(), 0)
        self.assertEqual(ledger._spent(SearchReservation.objects.all()), 100_000)

    def test_exact_settlement_releases_only_known_difference_in_original_month(self):
        first = self.reserve(price=self.make_price(100_000))
        self.clock.at = datetime(2026, 11, 1, tzinfo=dt_timezone.utc)
        settled = self.settle(first, 25_000)
        self.assertEqual(settled["held_microusd"], 0)
        self.assertEqual(settled["actual_charge_microusd"], 25_000)
        self.assertEqual(settled["month_start"], "2026-10-01")
        second = self.reserve(price=self.make_price(75_000))
        self.assertEqual(second["month_start"], "2026-11-01")
        self.assertEqual(ledger._spent(SearchReservation.objects.all()), 100_000)
        replay = self.settle(first, 25_000)
        self.assertTrue(replay["replayed"])
        with self.assertRaises(service.ThesisConflict):
            self.settle(first, 0)
        self.assertEqual(SearchSettlement.objects.count(), 1)

    def test_zero_release_requires_explicit_confirmation_and_named_active_staff(self):
        saved = self.reserve()
        with self.assertRaises(ValueError):
            ledger.settle_search(self.staff, saved["call_id"], 0,
                self.evidence(1), clock=self.clock)
        with self.assertRaises(service.ThesisUnavailable):
            ledger.settle_search(self.actor, saved["call_id"], 0,
                self.evidence(0), clock=self.clock)
        self.operator.is_active = False
        self.operator.save(update_fields=("is_active",))
        with self.assertRaises(service.ThesisUnavailable):
            self.settle(saved, 0)
        self.assertFalse(SearchSettlement.objects.exists())
        self.operator.is_active = True
        self.operator.save(update_fields=("is_active",))
        self.owner.is_active = False
        self.owner.save(update_fields=("is_active",))
        self.assertEqual(self.settle(saved, 0)["actual_charge_microusd"], 0)

    def test_foreign_staff_cannot_book_read_or_repurpose_another_owners_call(self):
        saved = self.reserve()
        for action in (
            lambda: self.reserve(actor=str(self.other.pk)),
            lambda: self.reserve(actor=str(self.other.pk), call=saved["call_id"]),
            lambda: ledger.get_reservation(str(self.other.pk), saved["call_id"]),
        ):
            with self.assertRaises(service.ThesisUnavailable):
                action()
        with self.assertRaises(service.ThesisConflict):
            self.reserve(price=self.make_price(20_000), call=saved["call_id"])
        with self.assertRaises(service.ThesisConflict):
            self.reserve(run=self.make_run(), call=saved["call_id"])
        self.assertEqual(SearchReservation.objects.count(), 1)

    def test_bad_unbounded_and_unreviewed_prices_never_admit(self):
        for bad in (True, 0, -1, 0.005, 100_001, None, "10000"):
            with self.assertRaises(ValueError):
                self.make_price(bad)
        document = self.price_document(10_000)
        for key, value in (("billing_basis", "variable_unknown"), ("currency", "EUR")):
            with self.assertRaises(ValueError):
                ledger.record_price_contract(self.staff, {**document, key: value}, clock=self.clock)
        with self.assertRaises(service.ThesisUnavailable):
            ledger.record_price_contract(self.actor, document, clock=self.clock)
        with self.assertRaises(service.ThesisConflict):
            ledger.reserve_search(self.actor, str(self.run.pk), str(uuid4()), "f" * 64, clock=self.clock)
        self.assertEqual(SearchReservation.objects.count(), 0)

    def test_settlement_cannot_exceed_maximum_or_replace_another_operators_decision(self):
        saved = self.reserve()
        with self.assertRaises(service.ThesisConflict):
            self.settle(saved, 10_001)
        self.settle(saved, 10_000)
        with self.assertRaises(service.ThesisConflict):
            ledger.settle_search(str(self.other.pk), saved["call_id"], 10_000,
                self.evidence(10_000), clock=self.clock)
        self.assertEqual(SearchSettlement.objects.get().actual_charge_microusd, 10_000)

    def _parallel(self, actions):
        barrier = Barrier(len(actions))
        def worker(action):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    return action()
                except ledger.SearchBudgetExhausted:
                    return "exhausted"
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            futures = [pool.submit(worker, action) for action in actions]
            return [future.result(timeout=20) for future in futures]

    def test_independent_connections_cannot_spend_last_investigation_cent_twice(self):
        self.reserve(price=self.make_price(90_000))
        results = self._parallel([self.reserve, self.reserve])
        self.assertEqual(results.count("exhausted"), 1)
        self.assertEqual(ledger._spent(SearchReservation.objects.filter(run=self.run)), 100_000)

    def test_independent_connections_share_last_monthly_cent_across_owners_and_providers(self):
        full = self.make_price(100_000)
        for index in range(99):
            self.reserve(run=self.make_run(), price=full)
        self.reserve(run=self.make_run(), price=self.make_price(90_000))
        other_run = self.make_run(self.other)
        other_price = self.make_price(10_000, "other_recorded_search")
        results = self._parallel([self.reserve,
            lambda: self.reserve(run=other_run, price=other_price, actor=str(self.other.pk))])
        self.assertEqual(results.count("exhausted"), 1)
        self.assertEqual(ledger._spent(SearchReservation.objects.all()), 10_000_000)

    def test_clock_is_sampled_after_waiting_for_shared_root_at_utc_month_rollover(self):
        waiting, sampled = Event(), Event()
        clock = Clock()
        clock.at = datetime(2026, 10, 31, 23, 59, 59, tzinfo=dt_timezone.utc)
        original_root = ledger._root
        def observed_root():
            waiting.set()
            return original_root()
        def trusted_clock():
            sampled.set()
            return clock.at
        def reserve_later():
            close_old_connections()
            try:
                return ledger.reserve_search(self.actor, str(self.run.pk), str(uuid4()),
                    self.price.pk, clock=trusted_clock)
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                ledger._root()
                with patch.object(ledger, "_root", side_effect=observed_root):
                    future = pool.submit(reserve_later)
                    self.assertTrue(waiting.wait(timeout=5))
                    self.assertFalse(sampled.is_set())
                    clock.at += timedelta(seconds=2)
            result = future.result(timeout=10)
        self.assertTrue(sampled.is_set())
        self.assertEqual(result["month_start"], "2026-11-01")
        self.assertEqual(result["created_at"], "2026-11-01T00:00:01+00:00")

    def test_database_guards_reject_rewrite_foreign_scope_bad_month_and_unpriced_charge(self):
        saved = self.reserve()
        row = SearchReservation.objects.get(pk=saved["call_id"])
        for mutation in (
            lambda: SearchReservation.objects.filter(pk=row.pk).update(maximum_charge_microusd=1),
            lambda: SearchReservation.objects.filter(pk=row.pk).delete(),
            lambda: SearchPriceContract.objects.filter(pk=self.price.pk).update(provider_id="rewritten"),
            lambda: SearchBudgetRoot.objects.filter(pk=1).delete(),
            lambda: SearchReservation.objects.create(id=uuid4(), owner=self.other, run=self.run,
                price_contract=self.price, maximum_charge_microusd=10_000,
                month_start=self.clock.at.date().replace(day=1), created_at=self.clock()),
            lambda: SearchReservation.objects.create(id=uuid4(), owner=self.owner, run=self.run,
                price_contract=self.price, maximum_charge_microusd=1,
                month_start=self.clock.at.date().replace(day=1), created_at=self.clock()),
            lambda: SearchReservation.objects.create(id=uuid4(), owner=self.owner, run=self.run,
                price_contract=self.price, maximum_charge_microusd=10_000,
                month_start=self.clock.at.date(), created_at=self.clock()),
            lambda: SearchSettlement.objects.create(reservation=row, actual_charge_microusd=0,
                operator=self.owner, provenance=self.evidence(0), recorded_at=self.clock()),
            lambda: SearchSettlement.objects.create(reservation=row, actual_charge_microusd=10_001,
                operator=self.operator, provenance=self.evidence(10_001), recorded_at=self.clock()),
        ):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    mutation()
        self.settle(saved, 0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SearchSettlement.objects.filter(pk=row.pk).update(actual_charge_microusd=1)

    def test_raw_independent_reservations_cannot_bypass_run_cap(self):
        self.reserve(price=self.make_price(90_000))
        def raw():
            try:
                SearchReservation.objects.create(id=uuid4(), owner=self.owner, run=self.run,
                    price_contract=self.price, maximum_charge_microusd=10_000,
                    month_start=self.clock.at.date().replace(day=1), created_at=self.clock())
                return "reserved"
            except IntegrityError:
                return "rejected"
        results = self._parallel([raw, raw])
        self.assertEqual(sorted(results), ["rejected", "reserved"])
        self.assertEqual(ledger._spent(SearchReservation.objects.all()), 100_000)

    def test_recorded_contract_identity_is_digest_of_exact_server_document(self):
        self.assertEqual(self.price.pk, text_digest(canonical_json(self.price.document)))
        repeated = self.make_price(10_000)
        self.assertEqual(repeated.reviewed_at, self.price.reviewed_at)
        self.assertEqual(SearchPriceContract.objects.count(), 1)
