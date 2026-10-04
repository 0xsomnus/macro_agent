"""Test-only SQLite ordering laboratory, not a production persistence choice.

Each writer takes SQLite's database write reservation before reading governing
state. Model calls and external delivery never run in these transactions.
"""

from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from macro_agent.domain.models import PinnedDependency, require_text
from macro_agent.domain.publication import (
    BriefState, PublicationCandidate, PublicationDecision, REQUIRED_ROLES,
    encode, pin_dict,
)
from macro_agent.domain.time import as_utc, parse_instant


_SCHEMA = """
CREATE TABLE IF NOT EXISTS briefs (
    brief_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
    generation INTEGER NOT NULL DEFAULT 0, changed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dependency_versions (
    brief_id TEXT NOT NULL REFERENCES briefs(brief_id), role TEXT NOT NULL,
    version_id TEXT NOT NULL, digest TEXT NOT NULL, known_at TEXT NOT NULL,
    PRIMARY KEY (brief_id, role, version_id)
);
CREATE TABLE IF NOT EXISTS dependency_heads (
    brief_id TEXT NOT NULL, role TEXT NOT NULL, version_id TEXT NOT NULL,
    PRIMARY KEY (brief_id, role),
    FOREIGN KEY (brief_id, role, version_id)
        REFERENCES dependency_versions(brief_id, role, version_id)
);
CREATE TABLE IF NOT EXISTS assessments (
    brief_id TEXT NOT NULL REFERENCES briefs(brief_id), assessment_id TEXT NOT NULL,
    digest TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL,
    reasons TEXT NOT NULL, reassessment_required INTEGER NOT NULL,
    observed_dependencies TEXT NOT NULL, saved_at TEXT NOT NULL,
    PRIMARY KEY (brief_id, assessment_id)
);
CREATE TABLE IF NOT EXISTS current_assessments (
    brief_id TEXT PRIMARY KEY, assessment_id TEXT NOT NULL,
    FOREIGN KEY (brief_id, assessment_id)
        REFERENCES assessments(brief_id, assessment_id)
);
CREATE TABLE IF NOT EXISTS brief_versions (
    brief_id TEXT NOT NULL, generation INTEGER NOT NULL,
    assessment_id TEXT NOT NULL, saved_at TEXT NOT NULL,
    PRIMARY KEY (brief_id, generation),
    FOREIGN KEY (brief_id, assessment_id)
        REFERENCES assessments(brief_id, assessment_id)
);
CREATE TABLE IF NOT EXISTS notification_intents (
    intent_id TEXT PRIMARY KEY, brief_id TEXT NOT NULL,
    assessment_id TEXT NOT NULL, state TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    FOREIGN KEY (brief_id, assessment_id)
        REFERENCES assessments(brief_id, assessment_id)
);
CREATE TABLE IF NOT EXISTS reassessment_work (
    brief_id TEXT NOT NULL REFERENCES briefs(brief_id), context_digest TEXT NOT NULL,
    reason TEXT NOT NULL, created_at TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending', completed_at TEXT,
    PRIMARY KEY (brief_id, context_digest)
);
CREATE TABLE IF NOT EXISTS audit (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    brief_id TEXT NOT NULL REFERENCES briefs(brief_id),
    kind TEXT NOT NULL, happened_at TEXT NOT NULL, detail TEXT NOT NULL
);
"""


def _pins(rows) -> tuple[PinnedDependency, ...]:
    return tuple(PinnedDependency(row["role"], row["version_id"], row["digest"],
                                  parse_instant(row["known_at"])) for row in rows)


def _dependencies(connection, brief_id):
    return _pins(connection.execute("""
        SELECT v.role, v.version_id, v.digest, v.known_at
        FROM dependency_heads h JOIN dependency_versions v
          USING (brief_id, role, version_id)
        WHERE h.brief_id = ? ORDER BY v.role
    """, (brief_id,)))


def _append_audit(connection, brief_id, kind, at, detail):
    connection.execute("""
        INSERT INTO audit (brief_id, kind, happened_at, detail) VALUES (?, ?, ?, ?)
    """, (brief_id, kind, as_utc(at).isoformat(), encode(detail)))


def _context_digest(dependencies):
    context = encode([pin_dict(pin) for pin in sorted(dependencies, key=lambda p: p.role)])
    return sha256(context.encode("utf-8")).hexdigest()


def _queue_reassessment(connection, brief_id, dependencies, at, reason):
    digest = _context_digest(dependencies)
    connection.execute("""
        INSERT OR IGNORE INTO reassessment_work
          (brief_id, context_digest, reason, created_at) VALUES (?, ?, ?, ?)
    """, (brief_id, digest, reason, as_utc(at).isoformat()))


class SQLitePublicationStore:
    """File-backed lab store with one fresh connection per transaction."""

    def __init__(self, path: str | Path, *, fail_before_intent: bool = False):
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("concurrency laboratory requires a file-backed database")
        self.fail_before_intent = fail_before_intent
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(_SCHEMA)
            # Identity/history tables cannot be rewritten even by adapter mistakes.
            for table in ("dependency_versions", "assessments", "brief_versions", "audit"):
                for operation in ("UPDATE", "DELETE"):
                    connection.execute(f"""
                        CREATE TRIGGER IF NOT EXISTS immutable_{table}_{operation.lower()}
                        BEFORE {operation} ON {table} BEGIN
                          SELECT RAISE(ABORT, 'immutable history');
                        END
                    """)

    @contextmanager
    def _connection(self, *, readonly=False):
        if readonly:
            uri = Path(self.path).resolve().as_uri() + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=10)
        else:
            connection = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        if readonly:
            connection.execute("PRAGMA query_only = ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _write(self):
        with self._connection() as connection:
            # This comes before every protected state/version read.
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    @contextmanager
    def transaction(self, brief_id: str):
        require_text(brief_id, "brief_id")
        with self._write() as connection:
            yield _Transaction(connection, brief_id, self.fail_before_intent)

    def bootstrap(self, brief_id: str, owner_id: str,
                  dependencies: tuple[PinnedDependency, ...], at: datetime):
        """Trusted fixture setup only; not a thesis approval or source adapter."""
        require_text(brief_id, "brief_id")
        require_text(owner_id, "owner_id")
        at = as_utc(at)
        if type(dependencies) is not tuple or any(not isinstance(p, PinnedDependency) for p in dependencies):
            raise TypeError("bootstrap requires validated immutable dependencies")
        if {p.role for p in dependencies} != REQUIRED_ROLES or len(dependencies) != len(REQUIRED_ROLES):
            raise ValueError("bootstrap must provide each required dependency role once")
        if any(pin.known_at > at for pin in dependencies):
            raise ValueError("bootstrap cannot activate future context")
        with self._write() as connection:
            connection.execute("INSERT INTO briefs VALUES (?, ?, 0, ?)",
                               (brief_id, owner_id, at.isoformat()))
            for pin in dependencies:
                connection.execute("INSERT INTO dependency_versions VALUES (?, ?, ?, ?, ?)",
                                   (brief_id, pin.role, pin.version_id, pin.digest, pin.known_at.isoformat()))
                connection.execute("INSERT INTO dependency_heads VALUES (?, ?, ?)",
                                   (brief_id, pin.role, pin.version_id))
            _append_audit(connection, brief_id, "bootstrap", at,
                          {"owner_id": owner_id, "dependencies": [pin_dict(p) for p in dependencies]})

    def advance_dependency(self, brief_id: str, pin: PinnedDependency, at: datetime):
        """Trusted fixture correction; all governing-state writers share _write."""
        if not isinstance(pin, PinnedDependency):
            raise TypeError("advance requires a validated dependency")
        at = as_utc(at)
        with self._write() as connection:
            state = _Transaction(connection, brief_id, False).state()
            if at < state.changed_at or pin.known_at > at:
                raise ValueError("dependency transition cannot be backdated")
            heads = {p.role: p for p in state.dependencies}
            if pin.role not in heads:
                raise ValueError("unknown governing dependency role")
            previous = heads[pin.role]
            existing = connection.execute("""
                SELECT role, version_id, digest, known_at FROM dependency_versions
                WHERE brief_id = ? AND role = ? AND version_id = ?
            """, (brief_id, pin.role, pin.version_id)).fetchone()
            if existing is not None and _pins((existing,))[0] != pin:
                raise ValueError("a dependency version cannot change digest or known_at")
            if previous == pin:
                return
            if existing is not None:
                # Every registered lab version has already been activated.
                # Equal known_at values cannot authorize restoring an old head.
                raise ValueError("a previously activated dependency version cannot become current again")
            if pin.known_at < previous.known_at:
                raise ValueError("a governing dependency cannot move backwards in known_at")
            if existing is None:
                connection.execute("INSERT INTO dependency_versions VALUES (?, ?, ?, ?, ?)",
                                   (brief_id, pin.role, pin.version_id, pin.digest, pin.known_at.isoformat()))
            connection.execute("""
                UPDATE dependency_heads SET version_id = ? WHERE brief_id = ? AND role = ?
            """, (pin.version_id, brief_id, pin.role))
            connection.execute("DELETE FROM current_assessments WHERE brief_id = ?", (brief_id,))
            connection.execute("UPDATE briefs SET changed_at = ? WHERE brief_id = ?", (at.isoformat(), brief_id))
            canceled = []
            pending = connection.execute("""
                SELECT n.intent_id, a.payload FROM notification_intents n
                JOIN assessments a USING (brief_id, assessment_id)
                WHERE n.brief_id = ? AND n.state = 'pending'
            """, (brief_id,)).fetchall()
            for row in pending:
                used = {p["role"]: p for p in json.loads(row["payload"])["dependencies"]}
                if used.get(pin.role) != pin_dict(pin):
                    connection.execute("""
                        UPDATE notification_intents SET state = 'canceled', updated_at = ?
                        WHERE intent_id = ?
                    """, (at.isoformat(), row["intent_id"]))
                    canceled.append(row["intent_id"])
            _queue_reassessment(connection, brief_id, _dependencies(connection, brief_id),
                                at, "changed:" + pin.role)
            _append_audit(connection, brief_id, "dependency_advanced", at,
                          {"previous": pin_dict(previous), "current": pin_dict(pin),
                           "canceled_intents": canceled})

    def mark_delivered(self, intent_id: str, at: datetime) -> bool:
        """Local lab acknowledgement with fresh pins; no external send guarantee."""
        at = as_utc(at)
        with self._write() as connection:
            row = connection.execute("""
                SELECT n.*, a.payload FROM notification_intents n
                JOIN assessments a USING (brief_id, assessment_id) WHERE n.intent_id = ?
            """, (intent_id,)).fetchone()
            if row is None:
                raise KeyError(intent_id)
            state = _Transaction(connection, row["brief_id"], False).state()
            if at < state.changed_at or at < parse_instant(row["updated_at"]):
                raise ValueError("delivery cannot be backdated")
            if row["state"] != "pending":
                return False
            used = json.loads(row["payload"])["dependencies"]
            current = [pin_dict(p) for p in state.dependencies]
            valid = sorted(used, key=lambda p: p["role"]) == current
            result = "delivered" if valid else "canceled"
            connection.execute("""
                UPDATE notification_intents SET state = ?, updated_at = ? WHERE intent_id = ?
            """, (result, at.isoformat(), intent_id))
            _append_audit(connection, row["brief_id"], "local_delivery_" + result, at,
                          {"intent_id": intent_id, "dependencies_current": valid})
            return valid

    def inspect(self, brief_id: str) -> dict:
        """Read-only consistent report; never creates audit, work or delivery state."""
        with self._connection(readonly=True) as connection:
            connection.execute("BEGIN")
            state = _Transaction(connection, brief_id, False).state()
            current = connection.execute("SELECT assessment_id FROM current_assessments WHERE brief_id = ?",
                                         (brief_id,)).fetchone()
            current_id = current[0] if current is not None else None
            assessments = []
            for row in connection.execute("SELECT * FROM assessments WHERE brief_id = ? ORDER BY rowid", (brief_id,)):
                assessments.append({"assessment_id": row["assessment_id"], "digest": row["digest"],
                                    "payload": json.loads(row["payload"]),
                                    "decision": {"status": row["status"], "reasons": json.loads(row["reasons"]),
                                                 "reassessment_required": bool(row["reassessment_required"])},
                                    "observed_dependencies": json.loads(row["observed_dependencies"]),
                                    "is_current": row["assessment_id"] == current_id, "saved_at": row["saved_at"]})
            report = {"brief_id": brief_id, "owner_id": state.owner_id, "generation": state.generation,
                      "changed_at": state.changed_at.isoformat(), "current_assessment_id": current_id,
                      "current_dependencies": [pin_dict(p) for p in state.dependencies],
                      "assessments": assessments}
            for label, table, order in (("dependency_history", "dependency_versions", "role, known_at, version_id"),
                                        ("brief_versions", "brief_versions", "generation"),
                                        ("notifications", "notification_intents", "created_at, intent_id"),
                                        ("reassessment", "reassessment_work", "created_at, context_digest")):
                report[label] = [dict(row) for row in connection.execute(
                    f"SELECT * FROM {table} WHERE brief_id = ? ORDER BY {order}", (brief_id,))]
            report["audit"] = [{**dict(row), "detail": json.loads(row["detail"])} for row in connection.execute(
                "SELECT * FROM audit WHERE brief_id = ? ORDER BY sequence", (brief_id,))]
            connection.commit()
            return report


class _Transaction:
    def __init__(self, connection, brief_id, fail_before_intent):
        self.connection = connection
        self.brief_id = brief_id
        self.fail_before_intent = fail_before_intent

    def state(self) -> BriefState:
        row = self.connection.execute("SELECT * FROM briefs WHERE brief_id = ?", (self.brief_id,)).fetchone()
        if row is None:
            raise KeyError(self.brief_id)
        return BriefState(row["owner_id"], row["generation"],
                          _dependencies(self.connection, self.brief_id), parse_instant(row["changed_at"]))

    def existing(self, assessment_id: str):
        row = self.connection.execute("""
            SELECT a.digest, a.status, a.reasons, a.reassessment_required,
                   c.assessment_id AS current_id FROM assessments a
            LEFT JOIN current_assessments c USING (brief_id)
            WHERE a.brief_id = ? AND a.assessment_id = ?
        """, (self.brief_id, assessment_id)).fetchone()
        if row is None:
            return None
        if row["status"] == "current" and row["current_id"] != assessment_id:
            return row["digest"], PublicationDecision("superseded", ("historical_publication",), False)
        return row["digest"], PublicationDecision(row["status"], tuple(json.loads(row["reasons"])),
                                                 bool(row["reassessment_required"]))

    def save(self, candidate: PublicationCandidate, decision: PublicationDecision, at: datetime):
        at = as_utc(at)
        state = self.state()
        if candidate.brief_id != self.brief_id or candidate.owner_id != state.owner_id:
            raise PermissionError("assessment belongs to a different brief or owner")
        self.connection.execute("""
            INSERT INTO assessments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (self.brief_id, candidate.assessment_id, candidate.digest, candidate.payload,
              decision.status, encode(list(decision.reasons)), decision.reassessment_required,
              encode([pin_dict(p) for p in state.dependencies]), at.isoformat()))
        canceled_intents = []
        if decision.status == "current":
            generation = state.generation + 1
            self.connection.execute("""
                UPDATE briefs SET generation = ?, changed_at = ? WHERE brief_id = ?
            """, (generation, at.isoformat(), self.brief_id))
            self.connection.execute("""
                INSERT INTO current_assessments VALUES (?, ?)
                ON CONFLICT (brief_id) DO UPDATE SET assessment_id = excluded.assessment_id
            """, (self.brief_id, candidate.assessment_id))
            self.connection.execute("INSERT INTO brief_versions VALUES (?, ?, ?, ?)",
                                    (self.brief_id, generation, candidate.assessment_id, at.isoformat()))
            self.connection.execute("""
                UPDATE reassessment_work SET state = 'completed', completed_at = ?
                WHERE brief_id = ? AND context_digest = ? AND state = 'pending'
            """, (at.isoformat(), self.brief_id, _context_digest(state.dependencies)))
            if candidate.material_change:
                canceled_intents = [row[0] for row in self.connection.execute("""
                    SELECT intent_id FROM notification_intents
                    WHERE brief_id = ? AND state = 'pending' ORDER BY intent_id
                """, (self.brief_id,)).fetchall()]
                self.connection.execute("""
                    UPDATE notification_intents SET state = 'canceled', updated_at = ?
                    WHERE brief_id = ? AND state = 'pending'
                """, (at.isoformat(), self.brief_id))
                if self.fail_before_intent:
                    raise RuntimeError("injected failure before notification intent")
                self.connection.execute("INSERT INTO notification_intents VALUES (?, ?, ?, 'pending', ?, ?)",
                                        (candidate.intent_id, self.brief_id, candidate.assessment_id,
                                         at.isoformat(), at.isoformat()))
        elif decision.reassessment_required:
            _queue_reassessment(self.connection, self.brief_id, state.dependencies, at, ",".join(decision.reasons))
        _append_audit(self.connection, self.brief_id, "publication", at,
                      {"assessment_id": candidate.assessment_id, "run_id": candidate.run_id,
                       "status": decision.status, "reasons": list(decision.reasons),
                       "pinned_dependencies": [pin_dict(p) for p in candidate.snapshot.dependencies],
                       "observed_dependencies": [pin_dict(p) for p in state.dependencies],
                       "canceled_intents": canceled_intents,
                       "intent_id": candidate.intent_id if decision.status == "current" else None})
