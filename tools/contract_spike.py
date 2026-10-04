"""Disposable contract laboratory, not the chosen product runtime.

All decisions and weights are synthetic fixture inputs. No models, sources,
credentials, market data, delivery channels, or production workers are used.
"""

import argparse
import copy
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def instant(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone required")
    return result


def digest(value):
    payload = value if isinstance(value, str) else json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_fixture():
    return json.loads((ROOT / "fixtures/pilot.json").read_text())


def materiality(screen):
    """Tests control routes only; these inputs are not an implemented classifier."""
    impact = screen["thesis_impact"] or screen["trade_impact"]
    severe_route = (
        screen["credible"] and screen["potential_severity"] == "high"
        and (screen["plausible_transmission"] or screen["broad_disruption"])
    )
    if not screen["classifier_available"] or not screen["resolved"]:
        route = "investigate" if severe_route or impact else "unresolved_queue"
    elif impact or severe_route:
        route = "investigate"
    else:
        route = "audit_only"
    # Novelty is deliberately absent from the route and interruption predicates.
    return {
        "route": route,
        "early_notice": bool(screen["credible"] and screen["urgent"] and (impact or severe_route)),
        "analysis_required": route == "investigate",
        "state": "resolved_low" if route == "audit_only" else "potential_or_unresolved",
    }


def accumulated(observations, driver_id, cutoff, window_seconds, threshold):
    upper = instant(cutoff)
    lower = upper - timedelta(seconds=window_seconds)
    distinct = {}
    for observation in observations:
        at = instant(observation["known_at"])
        if observation["driver_id"] == driver_id and lower <= at <= upper:
            key = observation["event_id"]
            if key in distinct and distinct[key] != observation:
                raise ValueError("conflicting duplicate must use an explicit revision")
            distinct[key] = observation
    score = round(sum(item["signed_fixture_weight"] for item in distinct.values()), 8)
    return {"event_ids": sorted(distinct), "signed_fixture_score": score, "material": abs(score) >= threshold}


class DeskSpike:
    def __init__(self, fixture):
        if fixture.get("synthetic") is not True:
            raise ValueError("laboratory accepts synthetic inputs only")
        self.fixture = copy.deepcopy(fixture)
        self.context_versions = {item["id"]: copy.deepcopy(item) for item in fixture["context_versions"]}
        if len(self.context_versions) != len(fixture["context_versions"]):
            raise ValueError("context version identities must be unique")
        self.owner_id = fixture["thesis"]["owner_id"]
        self.now = fixture["thesis"]["approved_at"]
        self.db = sqlite3.connect(":memory:")
        self.db.executescript("""
            CREATE TABLE theses (id TEXT PRIMARY KEY, text TEXT, text_hash TEXT);
            CREATE TABLE interpretations (id TEXT PRIMARY KEY, payload TEXT, meaning_hash TEXT);
            CREATE TABLE activations (id INTEGER PRIMARY KEY, interpretation_id TEXT, approved_at TEXT);
            CREATE TABLE events (id TEXT, revision INTEGER, payload TEXT, known_at TEXT, PRIMARY KEY(id, revision));
            CREATE TABLE assessments (id TEXT PRIMARY KEY, event_id TEXT, revision INTEGER,
                interpretation_id TEXT, payload TEXT, is_current INTEGER);
            CREATE TABLE notification_intents (id TEXT PRIMARY KEY, assessment_id TEXT,
                state TEXT, attempts INTEGER DEFAULT 0);
        """)
        thesis = fixture["thesis"]
        with self.db:
            self.db.execute("INSERT INTO theses VALUES (?, ?, ?)", (thesis["id"], thesis["text"], digest(thesis["text"])))

    def approve(self, interpretation, actor_id, actor_role, approved_at, text_hash, meaning_hash):
        if actor_role != "user" or actor_id != self.owner_id:
            raise PermissionError("only the thesis owner can approve meaning")
        stored_hash = self.db.execute("SELECT text_hash FROM theses").fetchone()[0]
        if text_hash != stored_hash or meaning_hash != digest(interpretation):
            raise ValueError("approval must bind the displayed exact text and meaning")
        instant(approved_at)
        if instant(approved_at) < instant(self.now):
            raise ValueError("activation cannot be backdated behind the system clock")
        with self.db:
            existing = self.db.execute("SELECT meaning_hash FROM interpretations WHERE id=?", (interpretation["id"],)).fetchone()
            if existing and existing[0] != meaning_hash:
                raise ValueError("interpretation versions are immutable")
            self.db.execute("INSERT OR IGNORE INTO interpretations VALUES (?, ?, ?)", (
                interpretation["id"], json.dumps(interpretation, sort_keys=True), meaning_hash
            ))
            self.db.execute("INSERT INTO activations (interpretation_id, approved_at) VALUES (?, ?)", (interpretation["id"], approved_at))
            self.db.execute("UPDATE assessments SET is_current=0 WHERE interpretation_id!=?", (interpretation["id"],))
            self.db.execute("UPDATE notification_intents SET state='superseded' WHERE state='pending' AND assessment_id IN (SELECT id FROM assessments WHERE interpretation_id!=?)", (interpretation["id"],))
        self.now = approved_at

    def active_at(self, cutoff):
        rows = self.db.execute("SELECT interpretation_id, approved_at, id FROM activations").fetchall()
        eligible = [row for row in rows if instant(row[1]) <= instant(cutoff)]
        if not eligible:
            return None
        return max(eligible, key=lambda row: (instant(row[1]), row[2]))[0]

    def ingest(self, event):
        if instant(event["known_at"]) < instant(event["system_received_at"]):
            raise ValueError("known_at cannot precede actual system receipt")
        instant(event["public_available_at"])
        payload = json.dumps(event, sort_keys=True)
        with self.db:
            existing = self.db.execute("SELECT payload FROM events WHERE id=? AND revision=?", (event["event_id"], event["revision"])).fetchone()
            if existing and existing[0] != payload:
                raise ValueError("same revision identity cannot overwrite source facts")
            if not existing:
                self.db.execute("INSERT INTO events VALUES (?, ?, ?, ?)", (event["event_id"], event["revision"], payload, event["known_at"]))
                # Any in-flight notice for a replaced revision loses its current status.
                newer = self.current_revision(event["event_id"], event["known_at"])
                self.db.execute("UPDATE assessments SET is_current=0 WHERE event_id=? AND revision<?", (event["event_id"], newer))
                self.db.execute("UPDATE notification_intents SET state='superseded' WHERE state='pending' AND assessment_id IN (SELECT id FROM assessments WHERE event_id=? AND revision<?)", (event["event_id"], newer))
        if instant(event["known_at"]) > instant(self.now):
            self.now = event["known_at"]
        return not bool(existing)

    def visible_events(self, cutoff):
        rows = self.db.execute("SELECT payload, known_at FROM events ORDER BY id, revision").fetchall()
        return [json.loads(payload) for payload, at in rows if instant(at) <= instant(cutoff)]

    def current_revision(self, event_id, cutoff):
        visible = [event["revision"] for event in self.visible_events(cutoff) if event["event_id"] == event_id]
        return max(visible, default=None)

    def publish(self, assessment_id, event, interpretation_id, at, fact_links, fail_before_intent=False, material_change=True):
        """One transaction publishes a current version and its durable intent."""
        if instant(at) < instant(self.now):
            raise ValueError("publication cannot be backdated behind known system state")
        if self.current_revision(event["event_id"], at) != event["revision"]:
            raise ValueError("stale source revision cannot become current")
        if self.active_at(at) != interpretation_id:
            raise ValueError("unapproved or stale interpretation cannot become current")
        stored = next(item for item in self.visible_events(at) if item["event_id"] == event["event_id"] and item["revision"] == event["revision"])
        if stored != event:
            raise ValueError("assessment input differs from immutable source record")
        decision = materiality(stored["screening"])
        if not stored["screening"]["credible"] or decision["route"] != "investigate":
            raise ValueError("screening does not permit a qualified notice")
        if not stored["screening"]["resolved"] and not decision["early_notice"]:
            raise ValueError("unresolved non-urgent investigation cannot interrupt")
        context_bindings = dict(self.fixture["context_bindings"], source_contract_version=event["source_contract_version"])
        context_records = {}
        for field, version_id in context_bindings.items():
            record = self.context_versions.get(version_id)
            if record is None or instant(record["known_at"]) > instant(at):
                raise ValueError("missing or future context cannot enter assessment")
            context_records[field] = {"id": version_id, "known_at": record["known_at"], "content_hash": digest(record["content"])}
        permissions = self.context_versions[event["source_contract_version"]]["content"].get("permitted_uses", [])
        if "display" not in permissions:
            raise PermissionError("source contract does not permit display")
        if not fact_links:
            raise ValueError("qualified notice requires a supported factual observation")
        for link in fact_links:
            if link["field"] not in stored["facts"] or stored["facts"][link["field"]] != link["value"]:
                raise ValueError("factual assertion must match its cited data field")
        interpretation = json.loads(self.db.execute("SELECT payload FROM interpretations WHERE id=?", (interpretation_id,)).fetchone()[0])
        thesis = self.db.execute("SELECT id, text_hash FROM theses").fetchone()
        brief_id = f"brief:{event['event_id']}:{thesis[0]}"
        payload = {
            "assessment_id": assessment_id, "kind": "qualified_notice", "at": at,
            "brief_id": brief_id, "brief_version": assessment_id,
            "material_change": material_change,
            "context": {"user_thesis_version": thesis[0], "text_hash": thesis[1],
                        "compiled_thesis_version": interpretation_id, "meaning_hash": digest(interpretation),
                        "event_version": [event["event_id"], event["revision"]],
                        **context_bindings, "version_records": context_records,
                        "model_version": None, "prompt_version": None},
            "facts": fact_links, "portfolio_impact": "unresolved", "expectations": "unavailable",
            "synthetic": True,
        }
        encoded = json.dumps(payload, sort_keys=True)
        intent_id = f"notice:{brief_id}:{assessment_id}" if material_change else None
        with self.db:
            existing = self.db.execute("SELECT payload FROM assessments WHERE id=?", (assessment_id,)).fetchone()
            if existing:
                if existing[0] != encoded:
                    raise ValueError("immutable assessment identity reused with different output")
                return intent_id
            self.db.execute("UPDATE assessments SET is_current=0 WHERE event_id=?", (event["event_id"],))
            if material_change:
                self.db.execute("UPDATE notification_intents SET state='superseded' WHERE state='pending' AND assessment_id IN (SELECT id FROM assessments WHERE event_id=?)", (event["event_id"],))
            self.db.execute("INSERT INTO assessments VALUES (?, ?, ?, ?, ?, 1)", (assessment_id, event["event_id"], event["revision"], interpretation_id, encoded))
            if fail_before_intent:
                raise RuntimeError("injected crash after assessment write")
            if intent_id:
                self.db.execute("INSERT INTO notification_intents VALUES (?, ?, 'pending', 0)", (intent_id, assessment_id))
        self.now = at
        return intent_id

    def deliver(self, intent_id, idempotent_sink, crash_after_send=False):
        row = self.db.execute("SELECT state FROM notification_intents WHERE id=?", (intent_id,)).fetchone()
        if row is None:
            raise KeyError(intent_id)
        if row[0] != "pending":
            return False
        with self.db:
            self.db.execute("UPDATE notification_intents SET attempts=attempts+1 WHERE id=?", (intent_id,))
        idempotent_sink.add(intent_id)
        if crash_after_send:
            raise RuntimeError("injected crash before delivery acknowledgement")
        with self.db:
            self.db.execute("UPDATE notification_intents SET state='delivered' WHERE id=?", (intent_id,))
        return True


def reference_trace():
    fixture = load_fixture()
    desk = DeskSpike(fixture)
    thesis, interpretation = fixture["thesis"], fixture["interpretation"]
    desk.approve(interpretation, thesis["owner_id"], "user", thesis["approved_at"], digest(thesis["text"]), digest(interpretation))
    trace = [{"step": "user_approval", "thesis_id": thesis["id"], "interpretation_id": interpretation["id"], "text_hash": digest(thesis["text"]), "meaning_hash": digest(interpretation)}]
    for event in fixture["events"]:
        trace.append({"step": "capture_and_screen", "event": [event["event_id"], event["revision"]], "new_receipt": desk.ingest(event), "public_available_at": event["public_available_at"], "system_received_at": event["system_received_at"], "known_at": event["known_at"], "decision": materiality(event["screening"])})
    original, correction, disruption, _ = fixture["events"]
    publication_at = desk.now
    try:
        desk.publish("stale-analysis", original, interpretation["id"], publication_at, [{"field": "reported_measure", "value": 3.1}])
    except ValueError as error:
        trace.append({"step": "stale_analysis_blocked", "reason": str(error)})
    intent_id = desk.publish("qualified-disruption-notice", disruption, interpretation["id"], publication_at, [{"field": "report", "value": disruption["facts"]["report"]}])
    sink = set()
    try:
        desk.deliver(intent_id, sink, crash_after_send=True)
    except RuntimeError:
        trace.append({"step": "send_before_ack_crash", "intent_id": intent_id})
    desk.deliver(intent_id, sink)
    trace.append({"step": "retry_same_notice", "external_identities": sorted(sink), "unique_notices": len(sink)})
    trace.append({"step": "frozen_assessment_context", "assessment": json.loads(desk.db.execute("SELECT payload FROM assessments WHERE id='qualified-disruption-notice'").fetchone()[0])})
    accumulation = fixture["accumulation"]
    for cutoff in ("2026-10-02T08:05:00Z", "2026-10-02T08:15:00Z", "2026-10-02T08:25:00Z"):
        trace.append({"step": "accumulate_with_offsets", "cutoff": cutoff, "result": accumulated(accumulation["observations"], "real_yields", cutoff, accumulation["window_seconds"], accumulation["threshold"])})
    desk.db.close()
    return {"synthetic": True, "scope": "contract mechanics only", "provider_calls": 0, "provider_spend": 0, "trace": trace}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = json.dumps(reference_trace(), indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")
