"""Mapping, reconciliation and run provenance for `pfa sync`.

The fetch layer itself cannot be tested without a real OAuth token, so it is kept deliberately thin;
everything below the network boundary is a pure function over archived-shaped payloads and is
tested here.  Run:  python3 -m unittest discover tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))

from pfa.finary import mapping  # noqa: E402

ASSETS = json.loads((HERE / "fixtures/rest_assets.json").read_text())
HOLDINGS = {k: v for k, v in json.loads((HERE / "fixtures/rest_holdings.json").read_text()).items()
            if not k.startswith("_")}
ACCOUNT_MAP = {"accounts": {"acc-pea": "pea", "acc-av": "assurance_vie", "acc-livret": "livret_a"},
               "ignore": ["acc-checking"]}


def run(root, *args):
    env = {**os.environ, "PFA_ROOT": str(root), "PYTHONPATH": str(PROJECT)}
    p = subprocess.run([sys.executable, "-m", "pfa", *args], env=env, capture_output=True, text=True)
    if p.returncode != 0:
        raise AssertionError(f"pfa {args} failed:\n{p.stdout}\n{p.stderr}")
    return p.stdout


class Mapping(unittest.TestCase):
    def build(self):
        return mapping.build_snapshot(ASSETS, HOLDINGS, ACCOUNT_MAP, run_id="run-test")

    def test_envelopes_and_perimeter(self):
        snap, _, _ = self.build()
        self.assertEqual({a["id"]: a["envelope"] for a in snap["accounts"]},
                         {"acc-pea": "pea", "acc-av": "assurance_vie", "acc-livret": "livret_a"})
        self.assertEqual(snap["run_id"], "run-test")

    def test_as_of_is_oldest_sync_not_today(self):
        """The valuation date follows the bank, not the machine clock."""
        snap, _, oldest = self.build()
        self.assertEqual(snap["as_of"], "2026-10-09")        # conn-1, not conn-2's 10-10
        self.assertEqual(oldest, "2026-10-09T18:30:00Z")
        import datetime as dt
        self.assertNotEqual(snap["as_of"], dt.date.today().isoformat())

    def test_opened_on_from_rest_only_field(self):
        snap, _, _ = self.build()
        pea = next(a for a in snap["accounts"] if a["id"] == "acc-pea")
        self.assertEqual(pea["opened_on"], "2019-03-15")

    def test_security_line(self):
        snap, _, _ = self.build()
        pea = next(a for a in snap["accounts"] if a["id"] == "acc-pea")
        self.assertEqual(len(pea["holdings"]), 1)            # the fiat line is omitted on purpose
        h = pea["holdings"][0]
        self.assertEqual(h["isin"], "LU1681043599")
        self.assertEqual(h["kind"], "etf")
        self.assertEqual(h["value"], 7000.0)
        self.assertEqual(h["cost_basis"], 5000.0)            # 10 x 500, a total not a per-unit PRU
        self.assertEqual(h["unit_price"], 700.0)

    def test_fonds_euros_has_no_isin_and_no_cost_basis(self):
        snap, _, _ = self.build()
        av = next(a for a in snap["accounts"] if a["id"] == "acc-av")
        fe = next(h for h in av["holdings"] if h["kind"] == "fonds_euros")
        self.assertIsNone(fe["isin"])
        self.assertIsNone(fe["cost_basis"])
        self.assertEqual(fe["value"], 500.0)

    def test_unknown_account_is_fatal(self):
        """A new Finary account is a decision, never an inference from its label."""
        partial = {"accounts": {"acc-pea": "pea"}, "ignore": []}
        with self.assertRaises(mapping.MappingError) as cm:
            mapping.build_snapshot(ASSETS, HOLDINGS, partial, run_id="r")
        self.assertIn("account_map.json", str(cm.exception))
        self.assertIn("acc-av", str(cm.exception))

    def test_unsupported_holding_type_is_fatal(self):
        """Dropping money silently is worse than failing."""
        doc = {"data": [{"id": "x", "type": "crypto-holdings",
                         "attributes": {"current_value": "1.0"}}], "included": []}
        with self.assertRaises(mapping.MappingError) as cm:
            mapping.build_snapshot(ASSETS, {**HOLDINGS, "acc-pea": doc}, ACCOUNT_MAP, run_id="r")
        self.assertIn("crypto-holdings", str(cm.exception))

    def test_non_eur_account_is_fatal(self):
        doc = json.loads(json.dumps(ASSETS))
        doc["data"][0]["attributes"]["currency"] = "USD"
        with self.assertRaises(mapping.MappingError):
            mapping.build_snapshot(doc, HOLDINGS, ACCOUNT_MAP, run_id="r")

    def test_broken_sync_is_relayed(self):
        doc = json.loads(json.dumps(ASSETS))
        doc["included"][0]["attributes"]["sync_status"] = "error"
        _, warns, _ = mapping.build_snapshot(doc, HOLDINGS, ACCOUNT_MAP, run_id="r")
        self.assertTrue(any("échec" in w and "Fortuneo" in w for w in warns), warns)


class Reconciliation(unittest.TestCase):
    def test_matches_finary_total(self):
        snap, _, _ = mapping.build_snapshot(ASSETS, HOLDINGS, ACCOUNT_MAP, run_id="r")
        overview = {"balance_sheet": {"owned_gross_assets_effective": "20500.00"}}
        rec = mapping.reconcile(snap, overview)
        self.assertEqual(rec["total"], 20500.0)              # 8000 + 3500 + 9000, checking ignored
        self.assertEqual(rec["gap"], 0.0)
        self.assertEqual(rec["gap_pct"], 0.0)

    def test_gap_beyond_tolerance_is_detected(self):
        snap, _, _ = mapping.build_snapshot(ASSETS, HOLDINGS, ACCOUNT_MAP, run_id="r")
        rec = mapping.reconcile(snap, {"balance_sheet": {"owned_gross_assets_effective": "25000.00"}})
        from pfa.sync import RECON_TOLERANCE
        self.assertGreater(rec["gap_pct"], RECON_TOLERANCE)

    def test_residual_becomes_the_cash_line(self):
        snap, _, _ = mapping.build_snapshot(ASSETS, HOLDINGS, ACCOUNT_MAP, run_id="r")
        rec = mapping.reconcile(snap, None)
        pea = next(p for p in rec["per_account"] if p["id"] == "acc-pea")
        self.assertEqual(pea["residual"], 1000.0)            # the omitted fiat line
        self.assertEqual(rec["overview_total"], None)

    def test_overview_without_balance_sheet_is_tolerated(self):
        snap, _, _ = mapping.build_snapshot(ASSETS, HOLDINGS, ACCOUNT_MAP, run_id="r")
        self.assertIsNone(mapping.reconcile(snap, {})["gap"])


class Provenance(unittest.TestCase):
    def _root(self, tmp):
        root = Path(tmp)
        (root / "profile").mkdir()
        (root / "profile" / "targets.json").write_text("{}")
        return root

    def test_run_id_reaches_every_financial_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            snap, _, _ = mapping.build_snapshot(ASSETS, HOLDINGS, ACCOUNT_MAP, run_id="run-abc")
            snap_file = root / "snap.json"
            snap_file.write_text(json.dumps(snap))
            run(root, "load-snapshot", str(snap_file))
            import sqlite3
            con = sqlite3.connect(root / "data" / "finance.db")
            for table in ("holdings", "account_values"):
                ids = {r[0] for r in con.execute(f"SELECT DISTINCT run_id FROM {table}")}
                self.assertEqual(ids, {"run-abc"}, table)
            self.assertEqual(con.execute("SELECT run_id FROM snapshots").fetchone()[0], "run-abc")
            seen = con.execute("SELECT DISTINCT first_seen_run_id, last_seen_run_id "
                               "FROM accounts").fetchall()
            self.assertEqual(seen, [("run-abc", "run-abc")])

    def test_legacy_snapshot_gets_a_synthetic_run(self):
        """A snapshot written before provenance existed still resolves to exactly one run."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            snap, _, _ = mapping.build_snapshot(ASSETS, HOLDINGS, ACCOUNT_MAP, run_id="x")
            snap.pop("run_id")
            f = root / "legacy.json"
            f.write_text(json.dumps(snap))
            run(root, "load-snapshot", str(f))
            import sqlite3
            con = sqlite3.connect(root / "data" / "finance.db")
            rid = con.execute("SELECT run_id FROM snapshots").fetchone()[0]
            self.assertEqual(rid, "legacy-2026-10-09")
            kind, status = con.execute("SELECT kind, status FROM runs WHERE run_id=?",
                                       (rid,)).fetchone()
            self.assertEqual((kind, status), ("legacy", "imported"))

    def test_ledger_survives_rebuild(self):
        """`rebuild` drops the DB, so the ledger — not the table — must be the source of truth."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            snap, _, _ = mapping.build_snapshot(ASSETS, HOLDINGS, ACCOUNT_MAP, run_id="run-xyz")
            f = root / "snap.json"
            f.write_text(json.dumps(snap))
            run(root, "load-snapshot", str(f))
            (root / "data" / "runs.jsonl").write_text(json.dumps({
                "run_id": "run-xyz", "kind": "snapshot", "status": "ok", "as_of": "2026-10-09",
                "started_at": "2026-10-09T19:00:00+00:00", "total_value": 20500.0,
                "overview_total": 20500.0, "recon_gap": 0.0, "transport": "rest+mcp"}) + "\n")
            run(root, "rebuild")
            import sqlite3
            con = sqlite3.connect(root / "data" / "finance.db")
            row = con.execute("SELECT kind, status, transport, recon_gap FROM runs "
                              "WHERE run_id='run-xyz'").fetchone()
            self.assertEqual(row, ("snapshot", "ok", "rest+mcp", 0.0))

    def test_failed_run_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            (root / "data").mkdir()
            (root / "data" / "runs.jsonl").write_text(
                json.dumps({"run_id": "r-fail", "kind": "snapshot", "status": "failed",
                            "error": "MappingError: compte inconnu"}) + "\n")
            run(root, "rebuild")
            out = run(root, "runs", "--json")
            rec = next(r for r in json.loads(out) if r["run_id"] == "r-fail")
            self.assertEqual(rec["status"], "failed")
            self.assertIn("compte inconnu", rec["error"])

    def test_truncated_ledger_line_is_skipped(self):
        """A hard crash mid-append must not make the whole ledger unreadable."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            (root / "data").mkdir()
            (root / "data" / "runs.jsonl").write_text(
                json.dumps({"run_id": "r-good", "kind": "snapshot", "status": "ok"}) + "\n"
                + '{"run_id": "r-trunc", "kind": "snap')
            out = run(root, "rebuild")
            self.assertIn("1 runs", out)


class PerimeterChanges(unittest.TestCase):
    """A closed account must not read as a loss."""

    def _two_snapshots(self, root, closed: dict | None = None):
        (root / "profile").mkdir(exist_ok=True)
        (root / "profile" / "targets.json").write_text("{}")
        (root / "profile" / "manual_inputs.json").write_text(json.dumps(
            {"closed_accounts": closed or {}}))
        snap, _, _ = mapping.build_snapshot(ASSETS, HOLDINGS, ACCOUNT_MAP, run_id="r1")
        f1 = root / "s1.json"
        f1.write_text(json.dumps(snap))
        run(root, "load-snapshot", str(f1))
        # second snapshot, a week later, with acc-livret gone
        later = json.loads(json.dumps(ASSETS))
        later["data"] = [a for a in later["data"] if a["id"] != "acc-livret"]
        for c in later["included"]:
            if c["type"] == "institution-connections":
                c["attributes"]["last_successful_sync_at"] = "2026-10-16T09:00:00Z"
        snap2, _, _ = mapping.build_snapshot(later, HOLDINGS, ACCOUNT_MAP, run_id="r2")
        f2 = root / "s2.json"
        f2.write_text(json.dumps(snap2))
        run(root, "load-snapshot", str(f2))
        return json.loads(run(root, "report", "--json"))

    def test_departed_account_is_reported_with_its_balance(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self._two_snapshots(Path(tmp))
            pc = r["perimeter_changes"]
            self.assertEqual([g["id"] for g in pc["gone"]], ["acc-livret"])
            self.assertEqual(pc["gone"][0]["last_balance"], 9000.0)
            self.assertEqual(pc["gone"][0]["last_seen"], "2026-10-09")
            self.assertIn("9 000.00 EUR", pc["note"])        # the amount that left the perimeter
            self.assertIn("pas lire comme une performance", pc["note"])

    def test_undeclared_departure_is_flagged_as_suspect(self):
        """Gone with no declared closure = possibly a broken sync, and must say so."""
        with tempfile.TemporaryDirectory() as tmp:
            r = self._two_snapshots(Path(tmp))
            g = r["perimeter_changes"]["gone"][0]
            self.assertIsNone(g["closed_on"])
            self.assertIn("sans clôture déclarée", r["perimeter_changes"]["note"])

    def test_declared_closure_carries_its_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self._two_snapshots(Path(tmp), closed={"acc-livret": {
                "closed_on": "2026-10-15", "transferred_to": "acc-pea",
                "note": "clôturé, solde transféré"}})
            g = r["perimeter_changes"]["gone"][0]
            self.assertEqual(g["closed_on"], "2026-10-15")
            self.assertEqual(g["transferred_to"], "acc-pea")
            self.assertEqual(g["reason"], "clôturé, solde transféré")
            self.assertNotIn("sans clôture déclarée", r["perimeter_changes"]["note"])

    def test_no_previous_snapshot_means_no_perimeter_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profile").mkdir()
            (root / "profile" / "targets.json").write_text("{}")
            snap, _, _ = mapping.build_snapshot(ASSETS, HOLDINGS, ACCOUNT_MAP, run_id="r1")
            f = root / "s.json"
            f.write_text(json.dumps(snap))
            run(root, "load-snapshot", str(f))
            r = json.loads(run(root, "report", "--json"))
            self.assertIsNone(r["perimeter_changes"]["note"])
            self.assertEqual(r["perimeter_changes"]["gone"], [])


class InstrumentDirHygiene(unittest.TestCase):
    def test_underscore_files_are_not_treated_as_instruments(self):
        """data/instruments/ also holds build helpers and archived intermediates."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profile").mkdir()
            (root / "profile" / "targets.json").write_text("{}")
            inst = root / "data" / "instruments"
            inst.mkdir(parents=True)
            (inst / "_scratch_aggregate.json").write_text(json.dumps({"countries": {"France": 100}}))
            (inst / "LU1681043599.json").write_text(json.dumps({
                "isin": "LU1681043599", "name": "Test", "kind": "etf", "ter": 0.0038,
                "pea_eligible": True, "breakdowns": {"asset_class": {"equity": 1.0}},
                "sources": [], "fetched_at": "2026-10-17"}))
            out = run(root, "rebuild")
            self.assertIn("1 instruments", out)


class ManualOpeningDates(unittest.TestCase):
    """Finary never serves opened_at, so the fiscal clocks depend on manual_inputs.json."""

    def test_opening_dates_drive_the_envelope_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profile").mkdir()
            (root / "profile" / "targets.json").write_text("{}")
            (root / "profile" / "manual_inputs.json").write_text(json.dumps({
                "account_opened_on": {"acc-av": "2017-12-14", "acc-pea": "2024-12-30"}}))
            snap, _, _ = mapping.build_snapshot(ASSETS, HOLDINGS, ACCOUNT_MAP, run_id="r1")
            f = root / "s.json"
            f.write_text(json.dumps(snap))
            run(root, "load-snapshot", str(f))
            r = json.loads(run(root, "report", "--json"))
            checks = {c["check"]: c for c in r["envelope_checks"]}
            self.assertTrue(checks["av_8y"]["ok"])            # 2017 -> mature
            self.assertFalse(checks["pea_5y"]["ok"])          # 2024 -> not yet
            self.assertGreater(checks["av_8y"]["value"], 8)
            # and they must survive the DB being dropped and replayed
            run(root, "rebuild")
            r2 = json.loads(run(root, "report", "--json"))
            self.assertTrue({c["check"] for c in r2["envelope_checks"]} >= {"av_8y", "pea_5y"})

    def test_a_malformed_date_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profile").mkdir()
            (root / "profile" / "targets.json").write_text("{}")
            (root / "profile" / "manual_inputs.json").write_text(json.dumps({
                "account_opened_on": {"acc-av": "14/12/2017"}}))     # wrong format
            snap, _, _ = mapping.build_snapshot(ASSETS, HOLDINGS, ACCOUNT_MAP, run_id="r1")
            f = root / "s.json"
            f.write_text(json.dumps(snap))
            with self.assertRaises(AssertionError):               # run() raises on non-zero exit
                run(root, "load-snapshot", str(f))


if __name__ == "__main__":
    unittest.main()
