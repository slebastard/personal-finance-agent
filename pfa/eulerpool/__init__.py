"""Eulerpool (api.eulerpool.com) enrichment: ETF constituents and company health, free plan.

What this package is for, and what it deliberately is not:

* It turns the fund ISINs the user holds into their top-N constituent companies and, for each, a
  normalised health record (profitability, margins, growth, quality scores, ESG).
* It is a *secondary, vendor* source. Every field carries its endpoint and fetch date, values the
  vendor gets visibly wrong are rejected at ingestion (never shown as zero), and nothing here is a
  recommendation.

Findings that shaped the design (measured 2026-11-01 on the free key):
a synthetic ETF's `etf/holdings` is its collateral basket, not its index, so the constituents of an
index come from a physical ETF tracking the same index (`profile/etf_proxies.json`); `etf/holdings`
costs thousands of quota units per call while a company call costs one.
"""
