"""Run provenance.

`data/runs.jsonl` is the source of truth; the `runs` table in SQLite is a queryable index of it,
rebuilt by `pfa rebuild`. Keeping the ledger outside the database matters: `rebuild` *drops* the
database, so provenance held only in SQL would be destroyed by the very command meant to restore
everything.

The ledger is append-only and one JSON object per line: it never rewrites history, it greps and
diffs, and a crash can at worst leave a truncated final line instead of corrupting a document.
Only the terminal state of a run is appended; on replay the last line for a given run_id wins, so
appending twice is harmless.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path

from . import DATA, db

LEDGER = DATA / "runs.jsonl"

FIELDS = ("run_id", "kind", "status", "started_at", "finished_at", "as_of", "transport",
          "raw_dir", "accounts_n", "holdings_n", "total_value", "overview_total",
          "recon_gap", "oldest_sync", "error")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def new(kind: str, transport: str | None = None) -> dict:
    """Start a run record. Nothing is written until `append` is called with its terminal state."""
    return {"run_id": str(uuid.uuid4()), "kind": kind, "status": "running",
            "started_at": now(), "transport": transport}


def append(run: dict, ledger: Path = LEDGER) -> None:
    """Append the run's terminal state. Written and fsync'd before the caller moves on."""
    run = {k: run.get(k) for k in FIELDS}
    run["finished_at"] = run.get("finished_at") or now()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(run, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def read_ledger(ledger: Path = LEDGER) -> list[dict]:
    """Every run, in ledger order, de-duplicated on run_id with the last line winning.

    A truncated final line (hard crash mid-append) is skipped rather than fatal.
    """
    if not ledger.exists():
        return []
    out: dict[str, dict] = {}
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue              # truncated tail; the log file in data/logs/ is the fallback trace
        if rec.get("run_id"):
            out[rec["run_id"]] = rec
    return list(out.values())


def replay(con) -> int:
    """Load the ledger into the `runs` table. Called by `pfa rebuild`."""
    runs = read_ledger()
    for r in runs:
        db.upsert_run(con, r)
    return len(runs)


def recent(con, limit: int = 20) -> list[dict]:
    rows = con.execute(
        "SELECT * FROM runs ORDER BY COALESCE(started_at, as_of) DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
