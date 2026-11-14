"""Bankin' CSV export (Profil → Export de données, offres Plus/Pro).

Observed format (export of 2026-10-18, 1 731 rows):

    separator  ';'
    columns    Date;Description;Compte;Montant;Catégorie;Sous-Catégorie;Note;Pointée
    date       DD/MM/YYYY
    amount     decimal point, negative = money out

Bankin' has no public API — `bankin.com/developers` is a 404 and `api.bankin.com` does not resolve;
only Bridge (their B2B arm) exposes one, under negotiated enterprise contracts. So a periodic CSV
export is the supported path, not a workaround.
"""
from __future__ import annotations

import csv
import datetime as dt
from collections import Counter
from pathlib import Path

SOURCE = "bankin-csv"
DELIM = ";"
REQUIRED = ("Date", "Description", "Compte", "Montant", "Catégorie", "Sous-Catégorie")


def sniff(path) -> bool:
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            header = fh.readline()
    except (OSError, UnicodeDecodeError):
        return False
    return all(c in header for c in ("Date", "Description", "Compte", "Montant"))


def parse(path) -> list[dict]:
    from . import row_id

    path = Path(path)
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=DELIM)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: colonnes manquantes {missing}. "
                             f"Colonnes vues : {reader.fieldnames}")
        rows = []
        seen = Counter()      # distinguishes genuinely repeated transactions, see row_id()
        for i, r in enumerate(reader, start=2):
            raw_date = (r["Date"] or "").strip()
            if not raw_date:
                continue
            try:
                date = dt.datetime.strptime(raw_date, "%d/%m/%Y").date().isoformat()
            except ValueError as e:
                raise ValueError(f"{path}:{i}: date illisible {raw_date!r} "
                                 f"(attendu JJ/MM/AAAA)") from e
            try:
                amount = round(float((r["Montant"] or "0").replace(",", ".")), 2)
            except ValueError as e:
                raise ValueError(f"{path}:{i}: montant illisible {r['Montant']!r}") from e
            label = (r["Description"] or "").strip()
            account = (r["Compte"] or "").strip()
            key = (date, label, amount, account)
            occurrence = seen[key]
            seen[key] += 1
            rows.append({
                "id": row_id(date, label, amount, account, occurrence),
                "date": date, "label": label, "account": account, "amount": amount,
                "category": (r.get("Catégorie") or "").strip() or None,
                "subcategory": (r.get("Sous-Catégorie") or "").strip() or None,
                "note": (r.get("Note") or "").strip() or None,
                "source": SOURCE,
            })
    return rows
