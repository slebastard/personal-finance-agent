"""pfa — personal finance agent toolkit (deterministic part).

Everything numeric lives here: the LLM agent fetches/maps data and narrates,
these modules validate, store, compute and render.
"""
import os
from pathlib import Path

# PFA_ROOT lets tests run against a throwaway directory
ROOT = Path(os.environ.get("PFA_ROOT") or Path(__file__).resolve().parent.parent)
DATA = ROOT / "data"
DB_PATH = DATA / "finance.db"
SNAPSHOTS = DATA / "snapshots"
INSTRUMENTS = DATA / "instruments"
RAW = DATA / "raw"
LOGS = DATA / "logs"
PROFILE = ROOT / "profile"
DASHBOARDS = ROOT / "dashboards"
JOURNAL = ROOT / "journal"
