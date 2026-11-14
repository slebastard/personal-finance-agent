"""Eulerpool enrichment: normalisation, caching, budget guard, look-through. No network.

The fake responses are INVENTED (shaped like the vendor's, with its quirks reproduced on purpose):
percent-vs-fraction units, zero valuation multiples, a 9999 Altman sentinel, HTML entities.
Run: python3 -m unittest discover tests
"""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))

from pfa import db, lookthrough, schema  # noqa: E402
from pfa.eulerpool import enrich, normalize as N  # noqa: E402
from pfa.eulerpool.client import QuotaExhausted  # noqa: E402

TODAY = dt.date(2026, 11, 14)
NOW = "2026-11-14T10:00:00+00:00"


def fake_company(isin, covered=True, **over):
    if not covered:
        return None
    ticker = {"US0000000001": "AAA", "US0000000002": "BBB", "NL0000000003": "CCC.PA"}.get(isin, "ZZZ")
    return {
        "profile": {"isin": isin, "name": f"Company {ticker} &amp; Co", "country": "US", "currency": "USD",
                    "sector": "Information Technology", "industry": "Semis &amp; Equipment",
                    "employees": 1000, "ipo": "2000-01-01", "mcap": 5000.5, "description": "Desc &amp; more"},
        "metrics": {"ticker": ticker, "currency": "USD",
                    "valuation": {"pe": 0, "ps": 0, "pebit": 0, "marketCap": 5000.5},
                    "profitability": {"roe": 0.5, "roa": 0.2, "roic": 0.4, "roce": 0.45,
                                      "grossMargin": 70.0, "operatingMargin": 40.0, "netMargin": 30.0},
                    "perShare": {"eps": 2.0, "dividendYield": 0.5},
                    "leverage": {"debtToEquity": 0.1, "netDebt": -100},
                    "historical": [{"year": y, "period": f"{y}-01-31", "revenue": 100 * (y - 2015),
                                    "ebit": 10, "netIncome": 8, "eps": 1, "roe": 0.3, "roa": 0.1, "roic": 0.2,
                                    "marketCap": 1} for y in range(2016, 2028)]},
        "margins": {"grossIncome_1y": 0.7, "grossIncome_3y": 0.69, "grossIncome_5y": 0.68, "grossIncome_10y": 0.6,
                    "ebit_1y": 0.4, "ebit_3y": 0.39, "ebit_5y": 0.38, "ebit_10y": 0.3,
                    "netIncome_1y": 0.3, "netIncome_3y": 0.29, "netIncome_5y": 0.28, "netIncome_10y": 0.2},
        "growth": {"revenue3Y": 1.0, "revenue5Y": 2.0, "revenue10Y": 5.0, "revenue3YPA": 0.26, "revenue5YPA": 0.25,
                   "revenue10YPA": 0.2, "ebit3Y": 1, "ebit5Y": 1, "ebit10Y": 1, "ebit3YPA": 0.1, "ebit5YPA": 0.1,
                   "ebit10YPA": 0.1, "income3Y": 1, "income5Y": 1, "income10Y": 1, "income3YPA": 0.1,
                   "income5YPA": 0.1, "income10YPA": 0.1},
        "aaqs": {"ticker": ticker, "score": 9, "revenueGrowth3Y": 0.26, "revenueGrowth10Y": 0.2,
                 "ebitGrowth3Y": 0.1, "ebitGrowth10Y": 0.1, "netDebtToEBIT": -0.5, "ebitMaxDrawdown10Y": -0.3,
                 "profitContinuity10Y": 10, "returnOnEquity": 0.5, "roce": 0.45, "expectedReturn": 0.9},
        "esg": {"environmentScore": 60, "socialScore": 70, "governanceScore": 90, "totalESGScore": 75,
                "co2EmissionScope1": 1, "co2EmissionScope2": 2, "co2EmissionScope3": 3, "co2EmissionTotal": 3,
                "tobacco": False, "militaryContract": "True", "catholic": True},
        "fair_value": {"fairValue": 120.0, "lastPrice": 100.0, "upside": 20.0},
        "quality": {"piotroski_score": 4, "altman_z": "9999.0000", "altman_zone": "safe", "period_date": "2026-01-31"},
        **over,
    }


def SNAP():
    return schema.validate_snapshot(json.loads((HERE / "fixtures/sample_snapshot_2.json").read_text()))[0]


class FakeClient:
    """Serves invented payloads and decrements a quota the way the real headers do."""

    def __init__(self, remaining=100_000, uncovered=()):
        self.calls, self.remaining, self.limit = 0, remaining, 100_000
        self.paths, self.uncovered = [], set(uncovered)

    def get(self, path):
        self.calls += 1
        self.paths.append(path)
        parts = path.split("/")
        if path.startswith("etf/holdings/"):
            self.remaining -= 4000
            return 200, [{"etf_symbol": "X", "isin": f"US000000000{i}", "name": f"CO {i}", "symbol": f"T{i}",
                          "percent": p, "updated_at": "2026-11-13T06:00:00Z"}
                         for i, p in ((1, 40.0), (2, 25.0), (3, 20.0))] + [
                {"isin": None, "name": "CASH", "percent": 15.0, "symbol": None}], self.remaining
        self.remaining -= 1
        if path.startswith("etf/sectors/"):
            return 200, [{"industry": "Technology", "exposure": 60.0}, {"industry": "Energy", "exposure": 40.0}], self.remaining
        if path.startswith("etf/countries/"):
            return 200, [{"country": "United States", "exposure": 100.0}], self.remaining
        key = {"profile": "profile", "metrics": "metrics", "margins": "margins", "growth": "growth",
               "aaqs": "aaqs", "esg-rating": "esg", "by-isin": "fair_value", "quality-scores": "quality"}
        endpoint = parts[1] if parts[0] != "fair-value" else "by-isin"
        ident = parts[-1]
        if ident in self.uncovered:
            return 404, {"error": "not found"}, self.remaining
        isin = ident if endpoint != "quality-scores" else None
        payload = fake_company(isin or "US0000000001")[key[endpoint]]
        return 200, payload, self.remaining


class Normalisation(unittest.TestCase):
    def test_company_units_rejections_and_flags(self):
        raw = fake_company("US0000000001")
        c = N.normalize_company("US0000000001", raw, NOW)
        self.assertEqual(c["name"], "Company AAA & Co")                  # HTML entity decoded
        self.assertAlmostEqual(c["metrics"]["net_margin"], 0.30)          # percent -> fraction
        self.assertAlmostEqual(c["metrics"]["roe"], 0.5)                  # already a fraction: untouched
        self.assertAlmostEqual(c["metrics"]["dividend_yield"], 0.005)
        self.assertNotIn("pe", c["metrics"])                              # zero multiples never stored
        self.assertIsNone(c["quality"]["altman"]["z"])                    # 9999 sentinel dropped
        self.assertTrue(any(f["field"] == "quality.altman" for f in c["flags"]))
        self.assertEqual(len(c["history"]), 10)                           # last ten fiscal years
        self.assertEqual(c["history"][-1]["year"], 2027)
        self.assertNotIn("marketCap", c["history"][0])
        self.assertAlmostEqual(c["vendor_models"]["upside"], 0.20)
        self.assertIs(c["esg"]["exposures"]["militaryContract"], True)    # "True" string -> bool
        self.assertTrue(c["covered"])

    def test_uncovered_company_is_flagged_not_zeroed(self):
        c = N.normalize_company("XX", {k: None for k in N.COMPANY_ENDPOINTS}, NOW)
        self.assertFalse(c["covered"])
        self.assertIsNone(c["metrics"]["roe"])
        self.assertTrue(any(f["field"] == "profile" for f in c["flags"]))

    def test_net_debt_ratio_is_dropped_when_ebit_is_not_positive(self):
        raw = fake_company("US0000000001")
        raw["metrics"]["profitability"]["operatingMargin"] = -5.0       # loss-making
        c = N.normalize_company("US0000000001", raw, NOW)
        self.assertIsNone(c["quality"]["aaqs"]["net_debt_to_ebit"])
        self.assertTrue(any("net_debt_to_ebit" in f["field"] for f in c["flags"]))
        ok = N.normalize_company("US0000000001", fake_company("US0000000001"), NOW)
        self.assertEqual(ok["quality"]["aaqs"]["net_debt_to_ebit"], -0.5)  # net cash with positive EBIT: kept

    def test_stale_piotroski_is_flagged(self):
        raw = fake_company("US0000000001")
        raw["quality"]["period_date"] = "2024-01-31"
        c = N.normalize_company("US0000000001", raw, NOW)
        self.assertTrue(any(f["field"] == "quality.piotroski" for f in c["flags"]))

    def test_holdings_ranking_and_coverage(self):
        rows = [{"isin": "A", "name": "a", "percent": 10.0}, {"isin": "B", "name": "b", "percent": 30.0},
                {"isin": None, "name": "cash", "percent": 20.0}, {"isin": "C", "name": "c", "percent": 40.0}]
        h = N.normalize_holdings("F", "P", "physical_proxy", rows, 2, NOW)
        self.assertEqual([c["isin"] for c in h["constituents"]], ["C", "B"])
        self.assertAlmostEqual(h["coverage_top"], 0.70)
        self.assertEqual(h["n_total"], 4)
        self.assertAlmostEqual(h["weights_sum"], 1.0)                      # the no-ISIN row still counts

    def test_crosscheck_gap_on_normalised_tables(self):
        from pfa import taxonomy
        held = {"Information Technology": 30.0, "Energy": 70.0}
        vendor = N.breakdown_table([{"industry": "Technology", "exposure": 35.0},
                                    {"industry": "Energy", "exposure": 65.0}], "industry", taxonomy.sector)
        self.assertAlmostEqual(N.crosscheck_tables(held, vendor), 5.0)
        self.assertIsNone(N.crosscheck_tables({}, vendor))

    def test_vendor_labels_fold_through_the_taxonomy(self):
        """Comparing raw labels produced a bogus 32-point gap on the first real run."""
        from pfa import taxonomy
        a = N.breakdown_table([{"industry": "Technology", "exposure": 32.5}], "industry", taxonomy.sector)
        b = N.breakdown_table([{"industry": "Information Technology", "exposure": 28.2}], "industry", taxonomy.sector)
        self.assertEqual(set(a), set(b))
        self.assertAlmostEqual(N.crosscheck_tables(a, b), 4.3)
        c = N.breakdown_table([{"country": "United Kingdom of Great Britain and Northern Ireland", "exposure": 3.3}],
                              "country", taxonomy.country)
        self.assertEqual(list(c), ["United Kingdom"])


class Stats(unittest.TestCase):
    def test_missing_values_are_excluded_not_zeroed(self):
        s = lookthrough.weighted_stats([(0.5, 10.0), (0.3, None), (0.2, 20.0)], denominator=1.0)
        self.assertAlmostEqual(s["mean"], (0.5 * 10 + 0.2 * 20) / 0.7)    # NOT divided by 1.0
        self.assertAlmostEqual(s["coverage"], 0.7)
        self.assertEqual(s["n"], 2)

    def test_weighted_quantiles(self):
        s = lookthrough.weighted_stats([(0.25, 1.0), (0.25, 2.0), (0.25, 3.0), (0.25, 4.0)])
        self.assertEqual((s["p25"], s["p50"], s["p75"]), (1.0, 2.0, 3.0))

    def test_empty(self):
        s = lookthrough.weighted_stats([(0.5, None)])
        self.assertIsNone(s["mean"])
        self.assertEqual(s["coverage"], 0.0)

    def test_quality_bucket_edges(self):
        self.assertEqual([lookthrough.quality_bucket(x) for x in (0, 1.9, 2, 7.9, 8, 10)], [0, 0, 1, 3, 4, 4])


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.saved = (enrich.HOLDINGS_DIR, enrich.COMPANIES_DIR, enrich.PROXIES_FILE, enrich.RAW)
        enrich.HOLDINGS_DIR, enrich.COMPANIES_DIR = root / "etf_holdings", root / "companies"
        enrich.PROXIES_FILE, enrich.RAW = root / "proxies.json", root / "raw"
        enrich.PROXIES_FILE.write_text(json.dumps({"funds": {
            "FR0011871128": {"kind": "self", "color_slot": 1},
            "LU1681043599": {"kind": "physical_proxy", "holdings_from": "IE00B4L5Y983", "index": "MSCI World",
                             "color_slot": 2}}}))
        self.con = db.connect(root / "t.db")
        db.load_snapshot(self.con, SNAP())
        # the held fund's own cited fiche is the crosscheck oracle
        ins = {"isin": "LU1681043599", "name": "Amundi MSCI World", "kind": "etf", "ter": 0.003,
               "pea_eligible": True, "replication": None, "index": "MSCI World", "issuer": "Amundi",
               "sri": 4, "performance": {}, "sources": [{"url": "https://x", "fetched_at": "2026-11-01"}],
               "fetched_at": "2026-11-01", "notes": None,
               "breakdowns": {"sector": {"Technologies de l'information": 0.6, "Énergie": 0.4},
                              "country": {"États-Unis": 1.0}}}
        db.load_instrument(self.con, ins)

    def tearDown(self):
        enrich.HOLDINGS_DIR, enrich.COMPANIES_DIR, enrich.PROXIES_FILE, enrich.RAW = self.saved
        self.tmp.cleanup()

    def run_enrich(self, client, **kw):
        return enrich.run(self.con, client, top=3, today=TODAY, log=lambda *_: None, **kw)

    def test_full_run_then_cache(self):
        c = FakeClient()
        s = self.run_enrich(c)
        self.assertIsNone(s["stopped"])
        self.assertEqual(len(list(enrich.HOLDINGS_DIR.glob("*.json"))), 2)
        self.assertEqual(len(list(enrich.COMPANIES_DIR.glob("*.json"))), 3)
        # two holdings pulls (one self, one proxy), 4 cross-check calls for the proxy, 3 x 8 company calls
        self.assertEqual(sum(p.startswith("etf/holdings/") for p in c.paths), 2)
        self.assertEqual(sum(p.startswith("equity/profile/") for p in c.paths), 3)
        doc = json.loads((enrich.HOLDINGS_DIR / "LU1681043599.json").read_text())
        self.assertEqual(doc["proxy_isin"], "IE00B4L5Y983")
        self.assertFalse(doc["crosscheck"]["warn"])
        self.assertAlmostEqual(doc["crosscheck"]["sector_max_gap_pts"], 0.0)      # 60/40 vs fake 60/40
        self.assertAlmostEqual(doc["crosscheck"]["country_max_gap_pts"], 0.0)
        # the held fund's side comes from our fiche, NOT from the vendor: no sectors/countries call for it
        self.assertNotIn("etf/sectors/LU1681043599", c.paths)
        # raw responses archived verbatim
        self.assertTrue(any(enrich.RAW.rglob("etf_holdings_*.json")))
        # second run: everything cached -> no network at all
        c2 = FakeClient()
        self.run_enrich(c2)
        self.assertEqual(c2.calls, 0)

    def test_renormalize_rebuilds_from_the_archive_without_any_call(self):
        self.run_enrich(FakeClient())
        p = enrich.COMPANIES_DIR / "US0000000001.json"
        doc = json.loads(p.read_text())
        doc["name"] = "CORRUPTED"
        doc["metrics"]["net_margin"] = 99.0
        p.write_text(json.dumps(doc))
        n = enrich.renormalize(self.con, log=lambda *_: None)
        self.assertEqual(n, 3)
        fixed = json.loads(p.read_text())
        self.assertEqual(fixed["name"], "Company AAA & Co")
        self.assertAlmostEqual(fixed["metrics"]["net_margin"], 0.30)
        self.assertEqual(fixed["fetched_at"], doc["fetched_at"])          # provenance date is kept

    def test_refresh_forces_refetch(self):
        self.run_enrich(FakeClient())
        c = FakeClient()
        self.run_enrich(c, force=True)
        self.assertGreater(c.calls, 0)

    def test_budget_guard_stops_before_the_expensive_call(self):
        c = FakeClient(remaining=enrich.RESERVE + 100)
        c.remaining = None                       # unknown at start, as with the real client
        c._start = enrich.RESERVE + 100
        real_get = c.get

        def get(path):
            if c.remaining is None:
                c.remaining = c._start
            return real_get(path)
        c.get = get
        s = self.run_enrich(c)
        self.assertIn("quota restant", s["stopped"])
        self.assertFalse(any(p.startswith("etf/holdings/") for p in c.paths))   # the costly call never went out

    def test_max_calls_cap(self):
        c = FakeClient()
        s = self.run_enrich(c, max_calls=3)
        self.assertIn("max-calls", s["stopped"])
        self.assertLessEqual(c.calls, 4)

    def test_a_malformed_company_does_not_abort_the_run(self):
        class Boom(FakeClient):
            def get(self, path):
                if path.startswith("equity/metrics/US0000000002"):
                    raise ValueError("bad payload")
                return super().get(path)
        c = Boom()
        s = self.run_enrich(c)
        self.assertEqual([e["isin"] for e in s["errors"]], ["US0000000002"])
        self.assertEqual(len(list(enrich.COMPANIES_DIR.glob("*.json"))), 2)    # the others were still written

    def test_path_segments_are_percent_encoded(self):
        from pfa.eulerpool.client import Client
        seen = []

        class Resp:
            status = 200
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b"{}"
        import urllib.request
        real = urllib.request.urlopen
        urllib.request.urlopen = lambda req, timeout=0: (seen.append(req.full_url), Resp())[1]
        try:
            Client(key="k").get("equity/quality-scores/NOVO B.CO")
        finally:
            urllib.request.urlopen = real
        self.assertTrue(seen[0].endswith("/equity/quality-scores/NOVO%20B.CO"))

    def test_uncovered_company_costs_one_call(self):
        c = FakeClient(uncovered={"US0000000003"})
        self.run_enrich(c)
        rec = json.loads((enrich.COMPANIES_DIR / "US0000000003.json").read_text())
        self.assertFalse(rec["covered"])
        self.assertEqual(sum(p == "equity/profile/US0000000003" for p in c.paths), 1)
        self.assertEqual(sum(p.endswith("US0000000003") for p in c.paths), 1)   # profile only: 404 ends it

    def test_dry_run_touches_nothing(self):
        s = enrich.run(self.con, None, top=3, today=TODAY, dry_run=True, log=lambda *_: None)
        self.assertGreater(s["estimate"]["calls"], 0)
        self.assertFalse(enrich.HOLDINGS_DIR.exists())

    def test_lookthrough_consolidates_and_reconciles(self):
        self.run_enrich(FakeClient())
        lt = lookthrough.lookthrough(self.con)
        self.assertEqual(len(lt["funds"]), 2)
        # every company exposure adds up to the identified euros (up to cent rounding per row)
        self.assertAlmostEqual(sum(c["exposure_eur"] for c in lt["companies"]), lt["identified_eur"], delta=0.05)
        # both funds list the same three companies -> each is held through two funds
        self.assertTrue(all(c["n_funds"] == 2 for c in lt["companies"]))
        self.assertEqual(lt["overlaps"][0]["common"], 3)
        self.assertAlmostEqual(lt["overlaps"][0]["overlap_weight"], 0.85)   # 0.40 + 0.25 + 0.20
        self.assertAlmostEqual(lt["identified_pct"], lt["identified_eur"] / lt["equity_value"])
        top = lt["companies"][0]
        self.assertAlmostEqual(top["exposure_eur"], sum(f["eur"] for f in top["funds"]), delta=0.02)

    def test_fund_companies_health_and_coverage(self):
        self.run_enrich(FakeClient())
        f = lookthrough.fund_companies(self.con, "LU1681043599")
        self.assertTrue(f["covered"])
        self.assertAlmostEqual(f["coverage_top"], 0.85)
        self.assertEqual(f["companies_with_data"], 3)
        self.assertAlmostEqual(f["health"]["net_margin"]["mean"], 0.30)
        self.assertAlmostEqual(f["health"]["net_margin"]["coverage"], 1.0)
        self.assertAlmostEqual(f["quality_distribution"][4]["weight"], 0.85)     # AAQS 9 -> top bucket
        self.assertEqual(f["constituents"][0]["rank"], 1)
        self.assertAlmostEqual(f["constituents"][0]["eur"], f["equity_value"] * 0.40, delta=0.01)

    def test_uncovered_fund_is_reported_with_a_reason(self):
        f = lookthrough.fund_companies(self.con, "LU1681043599")
        self.assertFalse(f["covered"])
        lt = lookthrough.lookthrough(self.con)
        self.assertEqual(lt["identified_eur"], 0)
        self.assertEqual(len(lt["funds_not_covered"]), 2)

    def test_rebuild_replays_documents(self):
        self.run_enrich(FakeClient())
        fresh = db.connect(Path(self.tmp.name) / "r.db")
        db.load_snapshot(fresh, SNAP())
        self.assertEqual(enrich.replay_from_disk(fresh), (2, 3))
        self.assertEqual(lookthrough.lookthrough(fresh)["n_companies"], 3)

    def test_company_view_where_held(self):
        self.run_enrich(FakeClient())
        v = lookthrough.company_view(self.con, "US0000000001")
        self.assertEqual(len(v["held"]["funds"]), 2)
        self.assertGreater(v["held"]["exposure_eur"], 0)
        self.assertIsNone(lookthrough.company_view(self.con, "NOPE"))


class RebuildKeepsTransactions(unittest.TestCase):
    """`pfa rebuild` drops the database file; transactions come from CSV imports it does not replay."""

    def test_transactions_survive_a_rebuild(self):
        import os
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "PFA_ROOT": tmp, "PYTHONPATH": str(PROJECT)}
            (Path(tmp) / "profile").mkdir()
            sh = lambda *a: subprocess.run([sys.executable, "-m", "pfa", *a], env=env, cwd=PROJECT,  # noqa: E731
                                           capture_output=True, text=True, check=True)
            sh("load-snapshot", str(HERE / "fixtures/sample_snapshot_2.json"))
            code = ("from pfa import db, runs\n"
                    "con = db.connect()\n"
                    "r = runs.new('transactions'); db.upsert_run(con, {**r, 'status': 'ok'})\n"
                    "db.load_transactions(con, [{'id': 'x1', 'date': '2026-01-02', 'label': 'L', 'account': 'A',"
                    " 'amount': -10.0, 'flow': 'spending', 'source': 'bankin-csv', 'category': 'c',"
                    " 'subcategory': 's', 'rule_id': None, 'note': None, 'period_month': None,"
                    " 'account_id': None}], r['run_id'])\n")
            subprocess.run([sys.executable, "-c", code], env=env, cwd=PROJECT, check=True)
            out = sh("rebuild").stdout
            self.assertIn("1 transactions", out)
            con = db.connect(Path(tmp) / "data" / "finance.db")
            self.assertEqual(con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 1)
            self.assertFalse((Path(tmp) / "data" / "finance.db.rebuild-backup").exists())


if __name__ == "__main__":
    unittest.main()
