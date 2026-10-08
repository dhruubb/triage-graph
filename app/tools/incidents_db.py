"""Past-incident database (SQLite) and the audit log for executed actions.

The incidents database is rebuilt from data/incidents.csv at startup and then opened
read-only for the agents. The audit log lives in a separate writable database.
"""

from __future__ import annotations

import csv
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from app.tools.sql_guard import MAX_ROWS, validate_select

SCHEMA = """
CREATE TABLE incidents (
    incident_id   TEXT PRIMARY KEY,
    opened_at     TEXT NOT NULL,
    service       TEXT NOT NULL,
    severity      TEXT NOT NULL,
    title         TEXT NOT NULL,
    symptoms      TEXT,
    root_cause    TEXT,
    resolution    TEXT,
    runbook_id    TEXT,
    mttr_minutes  INTEGER,
    status        TEXT
);
CREATE INDEX idx_incidents_service ON incidents(service);
CREATE INDEX idx_incidents_opened ON incidents(opened_at);
"""

SCHEMA_DOC = (
    "incidents(incident_id TEXT, opened_at TEXT ISO-8601, service TEXT, severity TEXT SEV1-SEV4, "
    "title TEXT, symptoms TEXT, root_cause TEXT, resolution TEXT, runbook_id TEXT, mttr_minutes INTEGER, status TEXT)"
)


def build_incidents_db(csv_path: Path, db_path: Path) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    try:
        con.executescript(SCHEMA)
        with csv_path.open(newline="") as f:
            rows = list(csv.DictReader(f))
        con.executemany(
            "INSERT INTO incidents VALUES (:incident_id, :opened_at, :service, :severity, :title, :symptoms,"
            " :root_cause, :resolution, :runbook_id, :mttr_minutes, :status)", rows)
        con.commit()
        return len(rows)
    finally:
        con.close()


class IncidentsDB:
    """Read-only access for the agents."""

    def __init__(self, db_path: Path, max_vm_steps: int = 2_000_000):
        self.path = db_path
        self._max_steps = max_vm_steps
        self._lock = threading.Lock()
        self._con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA query_only = ON")

    def _run(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        steps = {"n": 0}

        def guard() -> int:  # abort runaway queries
            steps["n"] += 1
            return 1 if steps["n"] * 1000 > self._max_steps else 0

        with self._lock:
            self._con.set_progress_handler(guard, 1000)
            try:
                cur = self._con.execute(sql, params)
                return [dict(r) for r in cur.fetchmany(MAX_ROWS)]
            finally:
                self._con.set_progress_handler(None, 0)

    def query(self, sql: str) -> list[dict]:
        """Run model-written SQL through the guard first."""
        return self._run(validate_select(sql))

    def count(self) -> int:
        return self._run("SELECT COUNT(*) AS n FROM incidents")[0]["n"]

    def reference_date(self) -> str:
        return self._run("SELECT MAX(opened_at) AS d FROM incidents")[0]["d"]

    def exists(self, incident_ids: list[str]) -> set[str]:
        if not incident_ids:
            return set()
        marks = ",".join("?" for _ in incident_ids)
        rows = self._run(f"SELECT incident_id FROM incidents WHERE incident_id IN ({marks})", tuple(incident_ids))
        return {r["incident_id"] for r in rows}

    def get(self, incident_ids: list[str]) -> list[dict]:
        if not incident_ids:
            return []
        marks = ",".join("?" for _ in incident_ids)
        return self._run(f"SELECT incident_id, title, root_cause, resolution FROM incidents WHERE incident_id IN ({marks})",
                         tuple(incident_ids))

    def similar(self, service: str, keywords: list[str], limit: int = 5) -> list[dict]:
        kws = [k.lower() for k in keywords if k and len(k) > 2][:8]
        score_terms = " + ".join(
            "(CASE WHEN lower(title || ' ' || symptoms || ' ' || root_cause) LIKE ? THEN 1 ELSE 0 END)" for _ in kws
        ) or "0"
        params: list[Any] = [f"%{k}%" for k in kws]
        sql = (f"SELECT incident_id, opened_at, service, severity, title, root_cause, resolution, runbook_id, mttr_minutes, "
               f"({score_terms}) AS matches FROM incidents WHERE service = ? "
               f"ORDER BY matches DESC, opened_at DESC LIMIT ?")
        params += [service, max(1, min(limit, 10))]
        rows = self._run(sql, tuple(params))
        return [r for r in rows if r["matches"] > 0] or rows[:3]

    def service_stats(self, service: str, days: int = 90) -> dict:
        ref = self.reference_date()
        window = f"-{max(1, min(days, 365))} days"
        base = "FROM incidents WHERE service = ? AND datetime(opened_at) >= datetime(?, ?)"
        p = (service, ref, window)
        by_sev = self._run(f"SELECT severity, COUNT(*) AS n {base} GROUP BY severity ORDER BY severity", p)
        mttr = self._run(f"SELECT ROUND(AVG(mttr_minutes)) AS avg_mttr, COUNT(*) AS total {base}", p)[0]
        causes = self._run(f"SELECT root_cause, COUNT(*) AS n {base} GROUP BY root_cause ORDER BY n DESC LIMIT 3", p)
        return {"service": service, "window_days": days, "as_of": ref, "total": mttr["total"],
                "avg_mttr_minutes": mttr["avg_mttr"], "by_severity": by_sev, "top_root_causes": causes}


class AuditLog:
    """Append-only record of actions the executor (simulated) ran."""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._con = sqlite3.connect(db_path, check_same_thread=False)
        self._con.execute(
            "CREATE TABLE IF NOT EXISTS actions (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, thread_id TEXT, "
            "ticket_id TEXT, step INTEGER, action TEXT, command TEXT, risk TEXT, approved_by TEXT, status TEXT, detail TEXT)")
        self._con.commit()

    def write(self, **row: Any) -> None:
        with self._lock:
            self._con.execute(
                "INSERT INTO actions (ts, thread_id, ticket_id, step, action, command, risk, approved_by, status, detail) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (time.time(), row.get("thread_id"), row.get("ticket_id"), row.get("step"), row.get("action"),
                 row.get("command"), row.get("risk"), row.get("approved_by"), row.get("status"),
                 json.dumps(row.get("detail", {}))))
            self._con.commit()

    def for_thread(self, thread_id: str) -> list[dict]:
        with self._lock:
            cur = self._con.execute("SELECT step, action, command, risk, approved_by, status FROM actions "
                                    "WHERE thread_id = ? ORDER BY step", (thread_id,))
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
