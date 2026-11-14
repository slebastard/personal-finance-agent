"""End-to-end test on fake fixtures, in a throwaway PFA_ROOT.  Run:  python3 -m unittest discover tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent


def run(root, *args):
    env = {**os.environ, "PFA_ROOT": str(root), "PYTHONPATH": str(PROJECT)}
    p = subprocess.run([sys.executable, "-m", "pfa", *args], env=env, capture_output=True, text=True)
    if p.returncode != 0:
        raise AssertionError(f"pfa {args} failed:\n{p.stdout}\n{p.stderr}")
    return p.stdout


class Pipeline(unittest.TestCase):
    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profile").mkdir()
            (root / "profile" / "targets.json").write_text(json.dumps(
                {"asset_class": {"equity": 0.7, "fonds_euros": 0.1, "cash": 0.2},
                 "region": {"North America": 0.6, "Europe ex-France": 0.2, "France": 0.1, "Emerging markets": 0.1}}))
            (root / "profile" / "manual_inputs.json").write_text(json.dumps(
                {"pea_contributions_total": {"acc-pea": 36000}, "account_fees": {"acc-av": 0.005}}))
            run(root, "load-snapshot", str(HERE / "fixtures/sample_snapshot_1.json"))
            run(root, "load-snapshot", str(HERE / "fixtures/sample_snapshot_2.json"))
            run(root, "load-instrument", str(HERE / "fixtures/instrument_FR0011871128.json"))
            r = json.loads(run(root, "report", "--json"))
            self.assertEqual(r["as_of"], "2026-10-01")
            self.assertAlmostEqual(r["total_value"], 23150 + 47500 + 31200, places=2)
            # PEA residual cash line synthesized (47500 - 45440)
            pea_cash = [p for p in r["positions"] if p["key"] == "acc-pea:cash"]
            self.assertAlmostEqual(pea_cash[0]["value"], 2060, places=2)
            # contributions of every line to a bucket add up to the headline exposure figure
            det = r["exposure_detail"]
            us = det["contributors"]["country:United States"]
            head = next((c for c in r["exposure"]["country"] if c["bucket"] == "United States"), None)
            self.assertAlmostEqual(sum(x["exposure_eur"] for x in us), head["value"] if head else 0.0, delta=0.05)
            self.assertAlmostEqual(sum(v["equity_value"] for v in det["by_envelope"].values()),
                                   r["exposure"]["equity_value"], delta=0.05)
            ac = {x["bucket"]: x["value"] for x in r["exposure"]["asset_class"]}
            self.assertAlmostEqual(ac["fonds_euros"], 18300, places=2)
            # LVMH -> France via ISIN proxy, ETF -> mostly North America
            reg = {x["bucket"]: x["value"] for x in r["exposure"]["region"]}
            self.assertAlmostEqual(reg["France"], 12800, places=2)
            self.assertGreater(reg["North America"], 31000)
            self.assertIn("Unclassified", reg)  # MSCI World not looked up yet
            gaps = json.loads(run(root, "gaps"))
            self.assertEqual(sorted(g["isin"] for g in gaps), ["FR0000121014", "LU1681043599"])  # stock needs sector too
            self.assertIsNotNone(r["returns"]["accounts"]["acc-pea"]["mwr_annualized"])
            self.assertEqual(r["returns"]["accounts"]["acc-pea"]["net_contributions"], 3600)
            checks = {c["check"]: c for c in r["envelope_checks"]}
            self.assertEqual(checks["pea_ceiling"]["headroom"], 114000)
            self.assertTrue(checks["pea_5y"]["ok"])
            self.assertFalse(checks["av_8y"]["ok"])
            # report carries the full instrument records the per-instrument pages need
            self.assertIn("FR0011871128", r["instruments"])
            self.assertIn("country", r["instruments"]["FR0011871128"]["breakdowns"])
            self.assertEqual(r["instruments"]["FR0011871128"]["pea_eligible"], True)
            run(root, "dashboard")
            html = (root / "dashboards" / "index.html").read_text()
            self.assertIn("Patrimoine financier", html)
            # envelope donut: one slice per funded envelope, colour fixed per envelope (not by rank)
            self.assertIn('class="donut"', html)
            self.assertIn("var(--cat-1)", html)          # PEA always slot 1
            live = [e for e in r["envelopes"] if e["value"] > 0]
            self.assertEqual(html.count('<g tabindex="0" data-tip='), len(live))
            self.assertEqual(html.count('<li><span class="sw"'), len(live))
            # one page per documented ISIN, linked from the index
            fiche = root / "dashboards" / "instruments" / "FR0011871128.html"
            self.assertTrue(fiche.exists())
            fhtml = fiche.read_text()
            self.assertIn("const CHARTS=", fhtml)
            self.assertIn("Ma position", fhtml)
            self.assertIn('href="../index.html"', fhtml)
            self.assertIn("instruments/FR0011871128.html", html)
            # an ISIN with no fiche gets neither a page nor a link
            self.assertFalse((root / "dashboards" / "instruments" / "FR0000121014.html").exists())
            self.assertNotIn("instruments/FR0000121014.html", html)
            # the dated archive copy sits a level down, so its links need the ../ prefix
            arch = (root / "dashboards" / "archive" / f"{r['as_of']}.html").read_text()
            self.assertIn("../instruments/FR0011871128.html", arch)
            plan = root / "plan.json"
            plan.write_text(json.dumps({"label": "t", "moves": [
                {"account_id": "acc-pea", "isin": "FR0011871128", "amount": 2000, "funded_by_cash": True},
                {"account_id": "acc-av", "isin": "IE00B4L5Y983", "name": "iShares Core MSCI World", "kind": "etf", "amount": 5000}]}))
            sim = json.loads(run(root, "simulate", str(plan)))
            self.assertAlmostEqual(sim["after"]["total_value"], r["total_value"] + 5000, places=2)
            self.assertAlmostEqual(sim["before"]["total_value"], r["total_value"], places=2)
            run(root, "rebuild")
            r2 = json.loads(run(root, "report", "--json"))
            self.assertEqual(r2["total_value"], r["total_value"])


if __name__ == "__main__":
    unittest.main()
