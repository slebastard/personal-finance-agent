"""Flow classification and aggregation. Run: python3 -m unittest discover tests"""
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

from pfa import flows  # noqa: E402
from pfa.importers import bankin, row_id  # noqa: E402

CSV = """Date;Description;Compte;Montant;Catégorie;Sous-Catégorie;Note;Pointée
31/03/2025;Vir Acme Corp;Compte Test;3500.00;Incomes;Salaries;;Non
30/09/2025;Vir Acme Corp;Compte Test;3600.00;Incomes;Refunds;;Non
11/10/2026;Vir Remplissage Livret A Pour Sa;Compte Test;-13391.00;Withdrawals;Transfer;;Non
12/10/2026;Vir Jean Dupont Cloture;Compte Test;8000.00;Incomes;Salaries;;Non
29/06/2026;Vir S/ Pea;Compte Test;-10000.00;Home;Rent;;Non
02/03/2026;CB Hotel Paris;Compte Test;-2500.00;Entertainment;Travels;;Non
15/03/2026;CB Monoprix;Compte Test;-27.90;Food & Dining;Supermarkets;;Non
15/03/2026;CB Monoprix;Compte Test;-27.90;Food & Dining;Supermarkets;;Non
"""

RULES = {"amount_review_threshold": 2000, "rules": [
    {"id": "salary-acme", "match_label": "acme corp", "flow": "income"},
    {"id": "livret-a-fill", "match_label": "remplissage livret", "flow": "internal"},
    {"id": "account-closure", "match_label": "cloture", "flow": "internal"},
    {"id": "pea-contribution", "match_label": "vir s/ pea", "flow": "internal"},
    {"id": "refunds-residual", "match_subcategory": "Refunds", "flow": "refund"},
]}


def write_csv(d: Path) -> Path:
    p = d / "export.csv"
    p.write_text(CSV, encoding="utf-8")
    return p


class Importer(unittest.TestCase):
    def test_parses_the_bankin_shape(self):
        with tempfile.TemporaryDirectory() as t:
            rows = bankin.parse(write_csv(Path(t)))
        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[0]["date"], "2025-03-31")      # DD/MM/YYYY -> ISO
        self.assertEqual(rows[0]["amount"], 3500.00)
        self.assertEqual(rows[0]["subcategory"], "Salaries")

    def test_identical_transactions_stay_distinct(self):
        """Two identical tolls on one day are two real transactions, not one."""
        with tempfile.TemporaryDirectory() as t:
            rows = bankin.parse(write_csv(Path(t)))
        monoprix = [r for r in rows if r["label"] == "CB Monoprix"]
        self.assertEqual(len(monoprix), 2)
        self.assertNotEqual(monoprix[0]["id"], monoprix[1]["id"])

    def test_id_ignores_the_category_so_recategorising_updates(self):
        a = row_id("2026-01-01", "CB Test", -10.0, "Compte")
        b = row_id("2026-01-01", "CB Test", -10.0, "Compte")
        self.assertEqual(a, b)
        self.assertNotEqual(a, row_id("2026-01-01", "CB Test", -10.0, "Autre"))


class Classification(unittest.TestCase):
    def klass(self, label, amount, sub=None, cat=None):
        return flows.classify({"label": label, "amount": amount,
                               "subcategory": sub, "category": cat}, RULES)

    def test_label_beats_the_bankin_subcategory(self):
        """The observed failure: Bankin' filed an account closure as a salary."""
        self.assertEqual(self.klass("Vir Jean Dupont Cloture", 8000.00, "Salaries"),
                         ("internal", "account-closure"))

    def test_salary_is_recognised_whatever_bankin_says(self):
        for sub in ("Salaries", "Refunds", "Other incomes"):
            self.assertEqual(self.klass("Vir Acme Corp", 3600.00, sub),
                             ("income", "salary-acme"), sub)

    def test_pea_contribution_is_not_rent(self):
        self.assertEqual(self.klass("Vir S/ Pea", -10000.0, "Rent", "Home"),
                         ("internal", "pea-contribution"))

    def test_large_unmatched_amount_is_forced_to_unclassified(self):
        flow, rule = self.klass("CB Hotel Paris", -2500.00, "Travels")
        self.assertEqual((flow, rule), ("unclassified", None))

    def test_small_unmatched_amount_falls_back_by_sign(self):
        self.assertEqual(self.klass("CB Monoprix", -27.90)[0], "spending")
        self.assertEqual(self.klass("Vir Inconnu", 42.0)[0], "income")

    def test_matching_ignores_case_and_accents(self):
        self.assertEqual(self.klass("VIR JEAN DUPONT CLÔTURE", 1.0)[0], "internal")


class Aggregation(unittest.TestCase):
    def test_end_to_end_against_the_cli(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "profile").mkdir()
            (root / "profile" / "targets.json").write_text("{}")
            (root / "profile" / "flow_rules.json").write_text(json.dumps(RULES))
            csv = write_csv(root)
            env = {**os.environ, "PFA_ROOT": str(root), "PYTHONPATH": str(PROJECT)}

            def run(*a):
                p = subprocess.run([sys.executable, "-m", "pfa", *a], env=env,
                                   capture_output=True, text=True)
                if p.returncode != 0:
                    raise AssertionError(f"pfa {a} failed:\n{p.stdout}\n{p.stderr}")
                return p.stdout

            run("import-transactions", str(csv))
            agg = json.loads(run("flows", "--json"))
            nat = agg["by_nature"]
            self.assertEqual(nat["income"]["count"], 2)              # both Acme lines
            self.assertEqual(nat["income"]["amount"], 7100.0)
            self.assertEqual(nat["internal"]["count"], 3)            # livret, closure, PEA
            self.assertEqual(nat["unclassified"]["count"], 1)        # Hotel, above threshold
            self.assertEqual(nat["spending"]["count"], 2)            # the two Monoprix
            # the PEA transfer must NOT appear as rent in the spending breakdown
            self.assertNotIn("Home", [c["category"] for c in agg["by_category"]])
            self.assertEqual(agg["quality"]["unclassified_count"], 1)

            # re-importing the same export changes nothing
            out = run("import-transactions", str(csv))
            self.assertIn("0 nouvelles", out.replace("chargé : ", "").replace(",", ""))

    def test_one_missed_salary_month_is_not_flagged(self):
        """A month-end salary legitimately slips into the next month; two in a row would not."""
        rows = [{"date": f"2026-{m:02d}-28", "flow": "income", "amount": 4200.0,
                 "account_id": None, "label": "x", "subcategory": None, "category": None}
                for m in (1, 2, 4, 5, 6)]          # March missing: paid on 2026-04-02
        rows.append({"date": "2026-03-01", "flow": "income", "amount": 60.0,
                     "account_id": None, "label": "y", "subcategory": None, "category": None})
        import sqlite3
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript("CREATE TABLE account_values(as_of TEXT, account_id TEXT, balance REAL);"
                          "CREATE TABLE transactions(label TEXT, category TEXT);")
        q = flows.quality(con, rows, "2026-01-01", "2026-06-30")
        self.assertEqual(q["months_with_suspicious_income"], [])


class BillingPeriod(unittest.TestCase):
    RULES = {"amount_review_threshold": 2000.0, "rules": [
        {"id": "salary", "match_label": "payroll", "flow": "income",
         "period": {"day_lte": 5, "shift_months": -1}}]}

    def _tx(self, date, label="Vir Payroll"):
        tx = {"date": date, "label": label, "amount": 4000.0, "category": None,
              "subcategory": None}
        flows.classify_all([tx], self.RULES)
        return tx

    def test_early_month_salary_belongs_to_previous_month(self):
        self.assertEqual(self._tx("2026-03-03")["period_month"], "2026-02")

    def test_january_wraps_to_previous_year(self):
        self.assertEqual(self._tx("2026-01-02")["period_month"], "2025-12")

    def test_month_end_salary_keeps_its_cash_month(self):
        self.assertIsNone(self._tx("2026-03-27")["period_month"])

    def test_rule_without_period_never_shifts(self):
        self.assertIsNone(self._tx("2026-03-03", "Autre")["period_month"])

    def test_only_income_is_reattributed(self):
        self.assertEqual(flows._month_of({"flow": "income", "date": "2026-03-03",
                                          "period_month": "2026-02"}), "2026-02")
        self.assertEqual(flows._month_of({"flow": "spending", "date": "2026-03-03",
                                          "period_month": "2026-02"}), "2026-03")


class Provisional(unittest.TestCase):
    def test_deposit_is_provisional_not_spending(self):
        # inline rules: the user's own flow_rules.json is private and absent from a fresh clone
        rules = {"amount_review_threshold": 2000.0, "rules": [
            {"id": "rental-deposit", "match_label": "caution rue exemple", "flow": "provisional"}]}
        tx = {"date": "2026-10-04", "label": "Vir Inst Caution Rue Exemple Caution Rue Exemple",
              "amount": -2000.0, "category": "Withdrawals, checks & transfer", "subcategory": "Checks"}
        flows.classify_all([tx], rules)
        self.assertEqual(tx["flow"], "provisional")
        self.assertIn("provisional", flows.NATURES)


if __name__ == "__main__":
    unittest.main()
