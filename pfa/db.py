"""SQLite store. The JSON files under data/ are the source of truth; the DB is rebuildable
with `python3 -m pfa rebuild`."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import DB_PATH

SCHEMA = """
-- Provenance. data/runs.jsonl is the source of truth; this table is its queryable index,
-- rebuilt from the ledger by `pfa rebuild`. Every financial row below carries a run_id.
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,                -- snapshot | lookup | legacy
  status TEXT NOT NULL,              -- ok | failed | imported
  started_at TEXT, finished_at TEXT,
  as_of TEXT,                        -- valuation date of the snapshot produced (NULL if it failed)
  transport TEXT,                    -- rest+mcp | mcp
  raw_dir TEXT,
  accounts_n INTEGER, holdings_n INTEGER,
  total_value REAL,
  overview_total REAL,               -- Finary's own authoritative figure, via MCP
  recon_gap REAL,                    -- total_value - overview_total
  oldest_sync TEXT,                  -- min(last_successful_sync_at) => real data freshness
  error TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
  as_of TEXT PRIMARY KEY, source TEXT, total_value REAL, loaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
  run_id TEXT REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY, name TEXT, institution TEXT, envelope TEXT, opened_on TEXT,
  first_seen_run_id TEXT REFERENCES runs(run_id),
  last_seen_run_id TEXT REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS account_values (
  as_of TEXT, account_id TEXT, balance REAL, run_id TEXT REFERENCES runs(run_id),
  PRIMARY KEY (as_of, account_id)
);
CREATE TABLE IF NOT EXISTS holdings (
  as_of TEXT, account_id TEXT, key TEXT, isin TEXT, name TEXT, kind TEXT,
  quantity REAL, unit_price REAL, value REAL, cost_basis REAL,
  run_id TEXT REFERENCES runs(run_id),
  PRIMARY KEY (as_of, account_id, key)
);
CREATE TABLE IF NOT EXISTS cash_flows (
  account_id TEXT, date TEXT, amount REAL, note TEXT, source TEXT,
  PRIMARY KEY (account_id, date, amount)
);
CREATE TABLE IF NOT EXISTS instruments (
  isin TEXT PRIMARY KEY, name TEXT, kind TEXT, ter REAL, pea_eligible INTEGER, replication TEXT,
  "index" TEXT, issuer TEXT, sri INTEGER, performance TEXT, sources TEXT, fetched_at TEXT, notes TEXT,
  run_id TEXT REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS instrument_breakdowns (
  isin TEXT, dimension TEXT, bucket TEXT, weight REAL, run_id TEXT REFERENCES runs(run_id),
  PRIMARY KEY (isin, dimension, bucket)
);
CREATE TABLE IF NOT EXISTS transactions (
  id          TEXT PRIMARY KEY,   -- hash(date|label|amount|account): re-importing is idempotent,
                                  -- and a recategorisation in Bankin' UPDATES instead of duplicating
  date        TEXT NOT NULL,
  label       TEXT NOT NULL,      -- the source of truth for classification, not the category
  account     TEXT NOT NULL,
  account_id  TEXT REFERENCES accounts(id),
  amount      REAL NOT NULL,      -- negative = money out
  category    TEXT,               -- Bankin' category, kept verbatim
  subcategory TEXT,
  flow        TEXT NOT NULL,      -- income | spending | internal | refund | provisional | unclassified
  rule_id     TEXT,               -- which rule decided: makes every classification auditable
  period_month TEXT,              -- YYYY-MM the flow BELONGS to when it differs from the cash date
                                  -- (salary paid 2026-03-03 is February's); NULL = date's month
  note        TEXT,
  source      TEXT NOT NULL,      -- importer id, e.g. 'bankin-csv'
  run_id      TEXT REFERENCES runs(run_id)
);
-- Eulerpool enrichment (vendor data). The JSON files under data/etf_holdings/ and data/companies/
-- are the source of truth; these tables hold the same documents so the server can read them.
CREATE TABLE IF NOT EXISTS etf_holdings (
  fund_isin TEXT PRIMARY KEY,         -- the ISIN the user HOLDS
  proxy_isin TEXT,                    -- the ETF whose lines stand in for it (itself, or a physical twin)
  kind TEXT, as_of TEXT, fetched_at TEXT,
  data TEXT NOT NULL,                 -- the data/etf_holdings/<ISIN>.json document
  run_id TEXT REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS companies (
  isin TEXT PRIMARY KEY, fetched_at TEXT,
  data TEXT NOT NULL,                 -- the data/companies/<ISIN>.json document
  run_id TEXT REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_tx_flow ON transactions(flow);
CREATE INDEX IF NOT EXISTS idx_tx_run ON transactions(run_id);
CREATE INDEX IF NOT EXISTS idx_holdings_run ON holdings(run_id);
CREATE INDEX IF NOT EXISTS idx_account_values_run ON account_values(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_as_of ON runs(as_of);
"""


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    # additive migration: CREATE TABLE IF NOT EXISTS does not add columns to an existing table
    if "period_month" not in {r[1] for r in con.execute("PRAGMA table_info(transactions)")}:
        con.execute("ALTER TABLE transactions ADD COLUMN period_month TEXT")
    return con


def upsert_run(con: sqlite3.Connection, run: dict) -> None:
    """Index one run from the ledger. Last write wins, so replaying a ledger is idempotent."""
    cols = ("run_id", "kind", "status", "started_at", "finished_at", "as_of", "transport",
            "raw_dir", "accounts_n", "holdings_n", "total_value", "overview_total",
            "recon_gap", "oldest_sync", "error")
    with con:
        con.execute(f"INSERT OR REPLACE INTO runs({','.join(cols)}) "
                    f"VALUES({','.join('?' * len(cols))})", tuple(run.get(c) for c in cols))


def load_snapshot(con: sqlite3.Connection, snap: dict) -> None:
    as_of = snap["as_of"]
    # a snapshot written before provenance existed is attached to a synthetic run, so that
    # every financial row still resolves to exactly one run_id
    run_id = snap.get("run_id") or f"legacy-{as_of}"
    if not snap.get("run_id"):
        upsert_run(con, {"run_id": run_id, "kind": "legacy", "status": "imported", "as_of": as_of,
                         "error": "snapshot predates run provenance"})
    with con:
        con.execute("DELETE FROM holdings WHERE as_of=?", (as_of,))
        con.execute("DELETE FROM account_values WHERE as_of=?", (as_of,))
        total = 0.0
        for a in snap["accounts"]:
            con.execute(
                "INSERT INTO accounts(id,name,institution,envelope,opened_on,"
                "first_seen_run_id,last_seen_run_id) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, institution=excluded.institution, "
                "envelope=excluded.envelope, opened_on=COALESCE(excluded.opened_on, accounts.opened_on), "
                "last_seen_run_id=excluded.last_seen_run_id",
                (a["id"], a["name"], a["institution"], a["envelope"], a["opened_on"], run_id, run_id))
            con.execute("INSERT INTO account_values VALUES(?,?,?,?)",
                        (as_of, a["id"], a["balance"], run_id))
            total += a["balance"]
            for h in a["holdings"]:
                con.execute("INSERT OR REPLACE INTO holdings VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (as_of, a["id"], h["key"], h["isin"], h["name"], h["kind"], h["quantity"],
                             h["unit_price"], h["value"], h["cost_basis"], run_id))
        for f in snap.get("cash_flows", []):
            con.execute("INSERT OR REPLACE INTO cash_flows VALUES(?,?,?,?,?)",
                        (f["account_id"], f["date"], f["amount"], f.get("note"), "snapshot"))
        con.execute("INSERT OR REPLACE INTO snapshots(as_of,source,total_value,run_id) "
                    "VALUES(?,?,?,?)", (as_of, snap["source"], round(total, 2), run_id))


def load_instrument(con: sqlite3.Connection, ins: dict, run_id: str | None = None) -> None:
    with con:
        con.execute("INSERT OR REPLACE INTO instruments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            ins["isin"], ins["name"], ins["kind"], ins["ter"],
            None if ins["pea_eligible"] is None else int(bool(ins["pea_eligible"])),
            ins["replication"], ins["index"], ins["issuer"], ins["sri"],
            json.dumps(ins["performance"]), json.dumps(ins["sources"], ensure_ascii=False),
            ins["fetched_at"], ins["notes"], run_id))
        con.execute("DELETE FROM instrument_breakdowns WHERE isin=?", (ins["isin"],))
        for dim, buckets in ins["breakdowns"].items():
            for bucket, w in buckets.items():
                con.execute("INSERT OR REPLACE INTO instrument_breakdowns VALUES(?,?,?,?,?)",
                            (ins["isin"], dim, bucket, w, run_id))


def load_etf_holdings(con: sqlite3.Connection, doc: dict, run_id: str | None = None) -> None:
    with con:
        con.execute("INSERT OR REPLACE INTO etf_holdings VALUES(?,?,?,?,?,?,?)",
                    (doc["fund_isin"], doc.get("proxy_isin"), doc.get("kind"), doc.get("as_of"),
                     doc.get("fetched_at"), json.dumps(doc, ensure_ascii=False), run_id))


def load_company(con: sqlite3.Connection, doc: dict, run_id: str | None = None) -> None:
    with con:
        con.execute("INSERT OR REPLACE INTO companies VALUES(?,?,?,?)",
                    (doc["isin"], doc.get("fetched_at"), json.dumps(doc, ensure_ascii=False), run_id))


TX_COLUMNS = ("id", "date", "label", "account", "account_id", "amount", "category", "subcategory",
              "flow", "rule_id", "period_month", "note", "source", "run_id")


def dump_transactions(con: sqlite3.Connection) -> list[dict]:
    """Every transaction exactly as stored (classification included), in a stable order."""
    have = {r[1] for r in con.execute("PRAGMA table_info(transactions)")}
    cols = [c for c in TX_COLUMNS if c in have]
    return [dict(zip(cols, r)) for r in con.execute(
        f"SELECT {','.join(cols)} FROM transactions ORDER BY date, id")]


def write_transactions_jsonl(con: sqlite3.Connection, path: Path) -> int:
    """data/transactions.jsonl: the portable source `pfa rebuild` replays. Atomic write."""
    rows = dump_transactions(con)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)
    return len(rows)


def load_transactions_jsonl(con: sqlite3.Connection, path: Path) -> int:
    """Replay data/transactions.jsonl into the table. Rows keep their stored flow and run_id."""
    if not path.exists():
        return 0
    n = 0
    required = ("id", "date", "label", "account", "amount", "flow", "source")
    with con:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            missing = [k for k in required if r.get(k) is None]
            if missing:
                raise ValueError(f"{path}: transaction sans {missing}: {str(r)[:120]}")
            cols = [c for c in TX_COLUMNS if c in r]
            con.execute(f"INSERT OR REPLACE INTO transactions({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                        tuple(float(r[c]) if c == "amount" else r[c] for c in cols))
            n += 1
    return n


def load_cash_flows(con: sqlite3.Connection, flows: list[dict]) -> None:
    with con:
        for f in flows:
            con.execute("INSERT OR REPLACE INTO cash_flows VALUES(?,?,?,?,?)",
                        (f["account_id"], f["date"], float(f["amount"]), f.get("note"),
                         "manual_inputs"))


def load_transactions(con: sqlite3.Connection, rows: list[dict], run_id: str) -> tuple[int, int]:
    """Upsert transactions. Returns (inserted, updated).

    The primary key is a hash of (date, label, amount, account) and deliberately excludes the
    category: when the user recategorises in Bankin' and re-exports, the existing row is updated rather
    than duplicated, so the correction loop is idempotent by construction.
    """
    ins = upd = 0
    with con:
        for r in rows:
            exists = con.execute("SELECT 1 FROM transactions WHERE id=?", (r["id"],)).fetchone()
            con.execute(
                "INSERT OR REPLACE INTO transactions"
                "(id,date,label,account,account_id,amount,category,subcategory,flow,rule_id,period_month,"
                " note,source,run_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["id"], r["date"], r["label"], r["account"], r.get("account_id"), r["amount"],
                 r.get("category"), r.get("subcategory"), r["flow"], r.get("rule_id"),
                 r.get("period_month"), r.get("note"), r["source"], run_id))
            upd += bool(exists)
            ins += not exists
    return ins, upd
