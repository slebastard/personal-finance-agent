---
name: review-transactions
description: Import a Bankin' CSV export, then point out the transactions Bankin' has probably miscategorised so the user can fix them in the app. Use after a half-monthly or monthly Bankin' export, when flow classification looks wrong, or when `pfa flows` reports unclassified amounts or suspicious income months.
---

# /review-transactions [export.csv] — the correction loop

Bankin' categorises **what** a transaction is; it does not say **what nature of flow** it is. Observed
on real exports — it can file an account closure as a salary:

```
12/10/2026  +8 000,00 €   Incomes / Salaries   « Vir Jean Dupont Cloture »
```

Your job: run the deterministic pass, then **judge** what it surfaces and hand the user a short,
prioritised list. They correct in Bankin', re-export, re-import. You never correct a category here.

## 1. Import

```
python3 -m pfa import-transactions <export.csv>          # add --dry-run to look first
```

The id is a hash of `(date, label, amount, account, occurrence)` and **excludes the category**, so a
recategorisation in Bankin' **updates** the existing row instead of duplicating it. The loop is
idempotent by construction — a re-import of an overlapping window is safe.

Before loading a partial re-export, it is worth checking the overlap: how many ids fall on existing
rows, how many are new, and whether any row in the window is missing from the new export (which
would leave a stale row behind). A sanity check beats discovering a duplicate later.

Read the import summary. It already gives the unclassified share, the reconciliation gap and any
suspicious-income month.

## 2. Get the candidates

```
python3 -m pfa flows --review [--start D --end D]        # --json for the full detail
```

Signals (each one was seen on real exports):

| Signal | What it caught |
|---|---|
| Internal-looking label classed as income/spending | a closed-account transfer filed as a salary |
| Amount ≥ the review threshold with no explicit rule | a very large one-off sitting in consumption |
| `Salaries` sub-category whose label is not a payroll line | same case |
| `Refunds` the size of a salary | a monthly payroll transfer filed as a refund |
| Same label categorised several ways | the employer transfer, filed under different categories |

Rows an explicit rule already decided are **excluded**: a deliberate choice is not a candidate.
Without that filter the list came back with 355 entries nobody would read.

## 3. Judge, then report

Do not relay the list raw. Work it:

- **Drop the false positives.** A transfer to a third party *is* spending. A large holiday payment
  above the threshold is real consumption.
- **Propose a target category** for each case you keep, and say why.
- **Rank by euros**, not by date. Ten euros mis-filed does not deserve a line.
- **Separate the two actions**: what the user must fix *in Bankin'* (a wrong category), versus what
  belongs in `profile/flow_rules.json` (a nature the label makes obvious).

Then give them 3–8 lines: what to recategorise in the app, what you propose to add as a rule, and the
residual that genuinely needs their arbitration — a large third-party inflow, a rental deposit,
anything whose nature only they know.

## 4. Turn recurrences into rules

**A correction that comes back every month must become a rule**, not a monthly re-flagging. Add it to
`profile/flow_rules.json` with its `_why`, then:

```
python3 -m pfa rebuild && python3 -m pfa import-transactions <export.csv>
```

Label rules win over sub-category rules, and the first match wins — so put the **specific** rule
before the general one. A real example: `vir intl` was classing « F Frais Vir Intl » as an internal
transfer, so a more specific `transfer-fees` rule had to come first; it recovered 108 € of real bank
fees that were disappearing from consumption.

## Rules of the house

- **Point, do not correct.** Bankin' is the source for categories. Rewriting one locally would be
  overwritten by the next export, and then nobody could tell which side was right.
- **Never guess a nature to make the figures look tidy.** An unclassified line is excluded from the
  totals and shown; that is the honest outcome, and `pfa flows` reports the share it represents.
- **The reconciliation gap validates completeness, not classification.** Σ flows must equal Δ balance
  between two snapshots; reclassifying a row does not change the sum. A gap means a truncated export
  or a missing month — a different problem from a wrong category.
- **A single month without income is not an anomaly**: a month-end payroll legitimately slips into
  the first days of the next month (observed: 2025-12-01, 2026-03-03, 2026-05-04). Only two
  consecutive low months are a real signal, and that is what the tool reports.
