"""What-if: apply trades/contributions to the latest snapshot and compare analytics before/after.

Plan file (JSON):
{
  "label": "Oct 2026: 3000 € new money",
  "moves": [
    {"account_id": "<id>", "isin": "FR0011871128", "name": "Amundi PEA S&P 500", "kind": "etf", "amount": 2000},
    {"account_id": "<id>", "key": "<holding key>", "amount": -500},          # sell part of a line
    {"account_id": "<livret id>", "amount": -1000}                            # cash in/out of an account balance
  ]
}
Positive amount = buy / deposit, negative = sell / withdraw. A buy in an account is funded by new money
(balance increases) unless "funded_by_cash": true, in which case the account's cash line is reduced.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from . import analytics, db


def _current_snapshot(con, as_of: str) -> dict:
    accounts = []
    for a in con.execute("SELECT a.*, v.balance FROM accounts a JOIN account_values v ON v.account_id=a.id "
                         "WHERE v.as_of=?", (as_of,)):
        hs = [dict(h) for h in con.execute("SELECT * FROM holdings WHERE as_of=? AND account_id=?", (as_of, a["id"]))]
        accounts.append({**dict(a), "holdings": hs})
    return {"as_of": as_of, "source": "simulation", "accounts": accounts, "cash_flows": []}


def run(con, plan: dict) -> dict:
    as_of = analytics.snapshot_dates(con)[-1]
    snap = _current_snapshot(con, as_of)
    sim = copy.deepcopy(snap)
    accts = {a["id"]: a for a in sim["accounts"]}
    for m in plan["moves"]:
        a = accts.get(m["account_id"])
        if a is None:
            raise SystemExit(f"unknown account_id {m['account_id']!r}; ids: {sorted(accts)}")
        amt = float(m["amount"])
        target_key = m.get("key") or m.get("isin")
        if not target_key:  # pure cash movement on a cash-like account
            line = next((h for h in a["holdings"] if h["kind"] == "cash"), None)
            if line is None:
                raise SystemExit(f"{a['name']}: no cash line to move cash in/out of")
            line["value"] += amt
            a["balance"] += amt
            continue
        line = next((h for h in a["holdings"] if h["key"] == target_key or (h["isin"] and h["isin"] == m.get("isin"))), None)
        if line is None:
            line = {"key": m.get("isin") or target_key, "isin": m.get("isin"), "name": m.get("name", target_key),
                    "kind": m.get("kind", "etf"), "quantity": None, "unit_price": None, "value": 0.0, "cost_basis": 0.0}
            a["holdings"].append(line)
        line["value"] += amt
        if amt > 0 and line["cost_basis"] is not None:
            line["cost_basis"] += amt
        if m.get("funded_by_cash"):
            cash = next((h for h in a["holdings"] if h["kind"] == "cash"), None)
            if cash is None or cash["value"] < amt:
                raise SystemExit(f"{a['name']}: not enough cash to fund {amt}")
            cash["value"] -= amt
        else:
            a["balance"] += amt
        if line["value"] < -0.01:
            raise SystemExit(f"{line['name']}: selling more than held")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "sim.db"
        con2 = db.connect(p)
        con.backup(con2)
        con2.row_factory = sqlite3.Row
        sim_as_of = (dt.date.fromisoformat(as_of) + dt.timedelta(days=1)).isoformat()  # synthetic date, temp DB only
        sim["as_of"] = sim_as_of
        for a in sim["accounts"]:
            for h in a["holdings"]:
                h.setdefault("key", h.get("isin"))
        db.load_snapshot(con2, sim)
        con2.execute("UPDATE snapshots SET source='simulation' WHERE as_of=?", (sim_as_of,))
        before = analytics.report(con, as_of)
        after = analytics.report(con2, sim_as_of)
        con2.close()

    def pick(r):
        return {"total_value": r["total_value"],
                "envelopes": r["envelopes"],
                "asset_class": r["exposure"]["asset_class"], "region": r["exposure"]["region"],
                "country": r["exposure"]["country"],
                "sector": r["exposure"]["sector"], "drift_vs_targets": r["drift_vs_targets"],
                "fees": r["fees"], "concentration": r["concentration"],
                "coverage": {k: v for k, v in r["exposure"]["data_gaps"].items() if k.startswith("coverage")}}
    return {"label": plan.get("label"), "based_on": as_of, "before": pick(before), "after": pick(after)}
