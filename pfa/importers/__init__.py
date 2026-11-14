"""Transaction importers, one module per source format, behind a common interface.

The source is expected to change — Bankin' today, maybe a bank export or an API later — so nothing
downstream of `parse()` knows where the rows came from. Each importer returns the same row shape:

    {id, date, label, account, amount, category, subcategory, note, source}

`id` is a stable hash of (date, label, amount, account, occurrence) and deliberately excludes the
category, so that recategorising in the source and re-importing updates the row instead of
duplicating it.

`occurrence` disambiguates genuinely repeated transactions — two identical tolls on the same day are
two real transactions, and hashing without it silently collapsed 12 rows of the first real import.
Exports are ordered, so the counter is stable across re-imports of an overlapping window.
"""
from __future__ import annotations

import hashlib

from . import bankin  # noqa: F401  (registers the format)

FORMATS = {"bankin-csv": bankin}


def row_id(date: str, label: str, amount: float, account: str, occurrence: int = 0) -> str:
    key = f"{date}|{label.strip().lower()}|{amount:.2f}|{account.strip().lower()}|{occurrence}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def detect(path) -> str:
    """Pick an importer by sniffing the file. Fails loudly rather than guessing wrong."""
    for name, mod in FORMATS.items():
        if mod.sniff(path):
            return name
    raise ValueError(
        f"{path}: unrecognised transaction export. Known formats: {', '.join(FORMATS)}. "
        f"Add an importer in pfa/importers/ rather than massaging the file by hand.")
