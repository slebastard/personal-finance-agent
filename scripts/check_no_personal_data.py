#!/usr/bin/env python3
"""Privacy guard: refuse to commit (or ship) anything that looks like the user's own data.

    python3 scripts/check_no_personal_data.py --staged    # what is about to be committed (pre-commit hook)
    python3 scripts/check_no_personal_data.py --all       # every tracked file (CI)
    python3 scripts/check_no_personal_data.py FILE...     # specific files

Three layers, because each catches what the others miss:
  1. PATHS    data/, journal/, dashboards/, a real profile/ file, .env, archives, databases…
  2. PATTERNS e-mail addresses, IBANs, API tokens and private keys, UUIDs that look like real account ids
  3. DENYLIST `.privacy-denylist` (git-ignored, one case-insensitive string per line): the user's own
              name, employer, account ids, counterparties. It lives on the user's machine only, which
              is the point: the public repo cannot hold the list of things it must not contain.

Exit status 1 and a list of findings when something is found; the snippet is redacted so the report itself
does not leak what it found. Stdlib only.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DENYLIST = ROOT / ".privacy-denylist"

FORBIDDEN_PATH = re.compile(
    r"^(data|journal|dashboards|exports|import)/|^\.env|\.(zip|db|pem|key)$|^PLAN-.*\.md$|^SPEC-.*\.md$|^\.privacy-denylist$")
PROFILE_OK = re.compile(r"^profile/[^/]+\.example\.[A-Za-z0-9]+$")
SKIP_CONTENT = re.compile(r"(^pnpm-lock\.yaml$|\.(png|jpg|jpeg|gif|ico|woff2?|ttf|svg|tsbuildinfo)$|^scripts/check_no_personal_data\.py$)")

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
EMAIL_OK = re.compile(r"@(users\.noreply\.github\.com|anthropic\.com|example\.(com|org)|test\.com)$|^noreply@|^git@")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")
TOKEN = re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|"
                   r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,})\b")
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
UUID_OK = re.compile(r"^(00000000|11111111|12345678|aaaaaaaa)-", re.I)


def iban_valid(raw: str) -> bool:
    """ISO 13616 mod-97 check: an ISIN or a reference number shaped like an IBAN almost never passes it."""
    s = raw.replace(" ", "")
    if not 15 <= len(s) <= 34:
        return False
    n = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(n) % 97 == 1


def tracked(mode: str, extra: list[str]) -> list[str]:
    if extra:
        return extra
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"] if mode == "staged" else ["git", "ls-files"]
    return [l for l in subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines() if l]


def staged_blob(path: str) -> str | None:
    p = subprocess.run(["git", "show", f":{path}"], cwd=ROOT, capture_output=True)
    return p.stdout.decode("utf-8", "replace") if p.returncode == 0 else None


def redact(s: str) -> str:
    s = s.strip()
    return (s[:3] + "…" + s[-2:]) if len(s) > 8 else "…"


def denylist() -> list[str]:
    if not DENYLIST.exists():
        return []
    return [l.strip().lower() for l in DENYLIST.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def scan(paths: list[str], mode: str) -> list[str]:
    deny = denylist()
    findings: list[str] = []
    for rel in paths:
        if FORBIDDEN_PATH.search(rel) or (rel.startswith("profile/") and not PROFILE_OK.match(rel)):
            findings.append(f"{rel}: chemin privé (données, profil réel, secret ou archive)")
            continue
        if SKIP_CONTENT.search(rel):
            continue
        text = staged_blob(rel) if mode == "staged" and not Path(rel).is_absolute() else None
        if text is None:
            f = ROOT / rel
            if not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
        for n, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            for m in EMAIL.finditer(line):
                if not EMAIL_OK.search(m.group(0)):
                    findings.append(f"{rel}:{n}: adresse e-mail ({redact(m.group(0))})")
            for m in IBAN.finditer(line):
                if iban_valid(m.group(0)):
                    findings.append(f"{rel}:{n}: IBAN ({redact(m.group(0))})")
            for m in TOKEN.finditer(line):
                findings.append(f"{rel}:{n}: jeton ou clé d'API ({redact(m.group(0))})")
            if PRIVATE_KEY.search(line):
                findings.append(f"{rel}:{n}: clé privée")
            for m in UUID.finditer(line):
                if not UUID_OK.match(m.group(0)):
                    findings.append(f"{rel}:{n}: UUID (identifiant de compte ?) ({redact(m.group(0))})")
            for term in deny:
                # whole-word match: "roye" must not fire inside "destroyed"
                if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", low):
                    findings.append(f"{rel}:{n}: terme de ta liste privée .privacy-denylist")
    return findings


def main(argv: list[str]) -> int:
    mode = "staged" if "--staged" in argv else "all"
    extra = [a for a in argv if not a.startswith("--")]
    paths = tracked(mode, extra)
    findings = scan(paths, mode)
    if findings:
        print(f"✗ {len(findings)} problème(s) de confidentialité dans {len(paths)} fichier(s) :", file=sys.stderr)
        for f in findings[:60]:
            print(f"  {f}", file=sys.stderr)
        print("\nCe dépôt ne contient que du code et des skills : les données de l'utilisateur voyagent par "
              "`python3 -m pfa export-data`, jamais par git.", file=sys.stderr)
        return 1
    print(f"✓ confidentialité : {len(paths)} fichier(s) vérifié(s), rien de personnel détecté"
          + ("" if DENYLIST.exists() else " (pas de .privacy-denylist locale : couche 3 inactive)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
