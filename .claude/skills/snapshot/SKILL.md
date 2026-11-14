---
name: snapshot
description: Refresh the portfolio from Finary by running the deterministic `pfa sync` script, then report the result. Use when the user asks to refresh/update/sync their data, or before any review/advice if the latest snapshot is older than ~7 days.
---

# /snapshot — run the sync script and report

The fetch-and-map pipeline is **no longer an agent task**: it is a deterministic script, so the
numbers never depend on how carefully a model transcribed a payload. Your job is to run it and
explain the outcome.

1. **Run it.**

   ```
   python3 -m pfa sync
   ```

   It fetches `/v1/assets` + `/v1/assets/{id}/holdings` over REST, reads `get_portfolio_overview`
   over MCP, archives every response verbatim to `data/raw/<as_of>/`, maps to a validated canonical
   snapshot, reconciles, loads into SQLite and refreshes the dashboard. Every row it writes carries
   a `run_id`.

2. **If it fails, do not work around it — diagnose it.** The error is already explicit. The common
   cases and their fixes:

   | Message | Fix |
   |---|---|
   | `no OAuth client registered` / `no refresh token` | ask the user to run `python3 -m pfa auth` (one-time login; it needs their browser) |
   | `refresh failed` | the refresh token was revoked → `python3 -m pfa auth` again |
   | `N compte(s) absent(s) de profile/account_map.json` | a new Finary account appeared. **Ask the user which envelope it is** — never infer it from the label — then add the id to `profile/account_map.json` |
   | `unsupported holding type` | a new asset class appeared. Ask the user whether to map it or add the account to `ignore` |
   | `écart de réconciliation … > 0.5 %` | a mapping error. Inspect `data/raw/<as_of>/`, find the cause, and fix the mapping. Do **not** pass `--force` to make it go away |

   Never hand-write a snapshot to bypass a failure: that reintroduces exactly the transcription risk
   the script removes.

3. **Check for gaps:** `python3 -m pfa gaps`. If ISINs are listed, offer `/lookup` (that one is still
   genuinely an agent task — it needs web research and source arbitration).

4. **Report back in 3–5 lines**, using only figures from `python3 -m pfa report`: total, Δ vs the
   previous snapshot, notable moves, data gaps. Mention the reconciliation gap and `as_of` when the
   valuation date is older than today — `as_of` is derived from the oldest successful bank sync, so
   it can legitimately lag. Relay any sync warning the script printed. No advice unless asked.

`python3 -m pfa runs` shows the run history if the user asks what happened, or when a cron run failed
silently overnight.
