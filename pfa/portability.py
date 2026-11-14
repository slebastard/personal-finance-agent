"""Export and import of EVERYTHING the application knows, as one zip archive.

Why this exists: the code lives in a public repository, the data does not. Moving to a new computer
(or recovering from a lost disk) means carrying the user's data separately and putting it back where the
application expects it. The SQLite file is deliberately NOT exported: it is rebuilt from the JSON and
JSONL sources (`pfa rebuild`), so the archive holds sources of truth only.

What is exported (relative to the project root) and why:

  profile/*                    private profile: accounts map, manual inputs, rules, targets, notes
  data/snapshots/*.json        canonical portfolio history (cannot be re-fetched: Finary has no history API)
  data/instruments/*.json      cited fund look-ups
  data/etf_holdings, companies enrichment documents (vendor data, personal local use)
  data/transactions.jsonl      every transaction exactly as classified (the replayable source)
  data/transactions/**         the original Bankin' CSV exports (provenance)
  data/runs.jsonl              the provenance ledger
  data/raw/**                  raw API responses, verbatim (provenance; `--no-raw` to leave them out)
  journal/**                   dated analyses, advice, plans

Never exported: API keys and the Finary refresh token (they live in the OS keychain), the OAuth client
registration (specific to one machine: `pfa auth` registers a new one), generated files (dashboards,
data/generated), logs, and the database itself.

The archive is NOT encrypted. It contains the user's whole financial picture: keep it somewhere safe.

An archive is treated as UNTRUSTED input on import: nothing in it is ever executed, every path is
checked against a whitelist (no absolute paths, no `..`, no symlinks, nothing outside the known
folders), every file must be listed in the manifest with a matching SHA-256, and no unlisted file
is accepted.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath

from . import ROOT, db

FORMAT = "pfa-export"
FORMAT_VERSION = 1
MANIFEST = "manifest.json"
PAYLOAD = "files/"

PRIVATE_PROFILE = ("account_map.json", "manual_inputs.json", "investor_profile.md", "targets.json",
                   "flow_rules.json", "etf_proxies.json", "learning.md", "decision_journal.md")
JSON_DIRS = ("data/snapshots", "data/instruments", "data/etf_holdings", "data/companies")
TREE_DIRS = ("data/transactions", "journal")          # copied recursively
RAW_DIR = "data/raw"
SINGLE_FILES = ("data/runs.jsonl", "data/transactions.jsonl")

MAX_ENTRIES = 100_000
MAX_TOTAL_BYTES = 4 * 1024 ** 3
MAX_MANIFEST_BYTES = 20 * 1024 ** 2
EXCLUDED = [
    {"what": "data/finance.db", "why": "reconstructible : `pfa rebuild` la recrée depuis les sources de vérité"},
    {"what": "trousseau (clé Eulerpool, jeton Finary)", "why": "secrets : jamais dans un fichier"},
    {"what": "data/oauth_client.json", "why": "enregistrement propre à une machine : `pfa auth` en crée un nouveau"},
    {"what": "dashboards/, data/generated/, data/logs/", "why": "fichiers générés"},
]


class ArchiveError(RuntimeError):
    """The archive is malformed, unsafe, or incompatible. Nothing has been written."""


class ImportConflict(RuntimeError):
    """The destination already holds different files. Re-run with --overwrite to replace them."""


# --------------------------------------------------------------------------- shared helpers

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_name_char(c: str) -> bool:
    return ord(c) >= 32 and ord(c) != 127 and c not in '\\:*?"<>|'


def allowed(rel: str) -> bool:
    """Whitelist of destinations an archive may write to (posix path relative to the project root)."""
    p = PurePosixPath(rel)
    parts = p.parts
    if not parts or rel.endswith("/"):
        return False
    if rel in SINGLE_FILES:
        return True
    top = "/".join(parts[:2])
    if parts[0] == "profile":
        return len(parts) == 2 and parts[1] in PRIVATE_PROFILE
    if top in JSON_DIRS:
        return len(parts) == 3 and parts[2].endswith(".json") and not parts[2].startswith("_")
    if rel.startswith(RAW_DIR + "/") or parts[0] == "journal" or top == "data/transactions":
        return len(parts) >= 2 and not any(x.startswith(".") for x in parts)
    return False


def _check_relpath(name: str) -> str:
    """Validate a posix path coming from an archive; return it normalised. Raises ArchiveError."""
    n = unicodedata.normalize("NFC", name)
    if "\\" in n or n.startswith("/") or (len(n) > 1 and n[1] == ":"):
        raise ArchiveError(f"chemin refusé (absolu ou séparateur invalide) : {name!r}")
    if not all(_safe_name_char(c) for c in n):
        raise ArchiveError(f"chemin refusé (caractère de contrôle ou interdit) : {name!r}")
    parts = PurePosixPath(n).parts
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise ArchiveError(f"chemin refusé (« . » ou « .. ») : {name!r}")
    return n


# --------------------------------------------------------------------------- export

def collect(root: Path, include_raw: bool = True) -> list[str]:
    """Project-relative posix paths of every file to export, sorted."""
    out: set[str] = set()

    def add(p: Path):
        if p.is_file() and not p.is_symlink():
            rel = p.relative_to(root).as_posix()
            if allowed(rel) and not any(x.startswith(".") or x == "__pycache__" for x in p.relative_to(root).parts):
                out.add(rel)

    for f in PRIVATE_PROFILE:
        add(root / "profile" / f)
    for d in JSON_DIRS:
        for p in sorted((root / d).glob("*.json")) if (root / d).is_dir() else []:
            add(p)
    for d in TREE_DIRS + ((RAW_DIR,) if include_raw else ()):
        base = root / d
        if base.is_dir():
            for p in sorted(base.rglob("*")):
                add(p)
    for f in SINGLE_FILES:
        add(root / f)
    return sorted(out)


def export_data(root: Path = ROOT, out: Path | None = None, include_raw: bool = True,
                now: dt.datetime | None = None, log=print) -> Path:
    """Write the archive and return its path. Refreshes data/transactions.jsonl from the database first."""
    root = Path(root)
    now = now or dt.datetime.now(dt.timezone.utc)
    db_path = root / "data" / "finance.db"
    n_tx = 0
    if db_path.exists():
        con = db.connect(db_path)
        try:
            n_tx = db.write_transactions_jsonl(con, root / "data" / "transactions.jsonl")
        finally:
            con.close()
    paths = collect(root, include_raw)
    if not paths:
        raise ArchiveError(f"rien à exporter sous {root} : pas de données ?")
    if out is None:
        out = root / "exports" / f"pfa-export-{now.strftime('%Y%m%d-%H%M%S')}.zip"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    files, counts = [], {}
    tmp = out.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in paths:
            src = root / rel
            info = zipfile.ZipInfo.from_file(src, PAYLOAD + rel)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o600) << 16          # private by default
            with open(src, "rb") as fh, zf.open(info, "w") as dst:
                shutil.copyfileobj(fh, dst, 1 << 20)
            files.append({"path": rel, "sha256": _sha256_file(src), "size": src.stat().st_size})
            top = "/".join(PurePosixPath(rel).parts[:2]) if rel.count("/") >= 2 else rel
            counts[top] = counts.get(top, 0) + 1
        manifest = {
            "format": FORMAT, "format_version": FORMAT_VERSION,
            "created_at": now.isoformat(timespec="seconds"),
            "include_raw": include_raw, "transactions": n_tx,
            "counts": dict(sorted(counts.items())), "files": files, "excluded": EXCLUDED,
            "notes": ["Archive NON chiffrée : elle contient toute ta situation financière.",
                      "Import : `python3 -m pfa import-data <archive>` ou `python3 -m pfa setup`."],
        }
        zf.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1))
    os.chmod(tmp, 0o600)
    os.replace(tmp, out)
    size = out.stat().st_size
    log(f"archive écrite : {out}  ({size / 1024:.0f} Ko, {len(files)} fichiers)")
    for k, v in sorted(counts.items()):
        log(f"  {k:<28} {v}")
    log("⚠ Archive NON chiffrée : elle contient toute ta situation financière. Range-la en lieu sûr "
        "(disque chiffré, coffre-fort) et ne la committe jamais.")
    return out


# --------------------------------------------------------------------------- import

def validate_archive(path: Path) -> tuple[dict, dict[str, zipfile.ZipInfo]]:
    """Check an archive end to end WITHOUT extracting anything. Returns (manifest, {rel: ZipInfo})."""
    path = Path(path)
    if not path.is_file():
        raise ArchiveError(f"archive introuvable : {path}")
    if not zipfile.is_zipfile(path):
        raise ArchiveError(f"{path.name} n'est pas une archive zip")
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ArchiveError(f"trop d'entrées ({len(infos)}) : archive refusée")
        if sum(i.file_size for i in infos) > MAX_TOTAL_BYTES:
            raise ArchiveError("taille décompressée excessive : archive refusée")
        names = [i.filename for i in infos]
        if len(set(names)) != len(names):
            raise ArchiveError("entrées en double dans l'archive")
        if MANIFEST not in names:
            raise ArchiveError("manifest.json absent : ce n'est pas une archive de cette application")
        mi = zf.getinfo(MANIFEST)
        if mi.file_size > MAX_MANIFEST_BYTES:
            raise ArchiveError("manifest trop volumineux")
        try:
            manifest = json.loads(zf.read(MANIFEST))
        except json.JSONDecodeError as e:
            raise ArchiveError(f"manifest illisible : {e}") from e
        if manifest.get("format") != FORMAT:
            raise ArchiveError(f"format inattendu : {manifest.get('format')!r}")
        ver = manifest.get("format_version")
        if not isinstance(ver, int) or ver > FORMAT_VERSION:
            raise ArchiveError(f"archive de format v{ver}, cette version ne lit que jusqu'à v{FORMAT_VERSION} : "
                               "mets l'application à jour (git pull) avant d'importer")
        listed = manifest.get("files")
        if not isinstance(listed, list):
            raise ArchiveError("manifest sans liste de fichiers")

        by_rel: dict[str, zipfile.ZipInfo] = {}
        for i in infos:
            if i.filename == MANIFEST or i.is_dir():
                if i.is_dir() and not i.filename.startswith(PAYLOAD):
                    raise ArchiveError(f"répertoire hors de files/ : {i.filename!r}")
                continue
            if not i.filename.startswith(PAYLOAD):
                raise ArchiveError(f"entrée hors de files/ : {i.filename!r}")
            if i.flag_bits & 0x1:
                raise ArchiveError(f"entrée chiffrée non supportée : {i.filename!r}")
            if (i.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
                raise ArchiveError(f"lien symbolique refusé : {i.filename!r}")
            rel = _check_relpath(i.filename[len(PAYLOAD):])
            if not allowed(rel):
                raise ArchiveError(f"destination non autorisée : {rel!r}")
            by_rel[rel] = i

        expected = {}
        for f in listed:
            if not isinstance(f, dict) or not isinstance(f.get("path"), str):
                raise ArchiveError("entrée de manifest invalide")
            rel = _check_relpath(f["path"])
            if rel in expected:
                raise ArchiveError(f"fichier listé deux fois : {rel!r}")
            expected[rel] = f
        if set(expected) != set(by_rel):
            extra = sorted(set(by_rel) - set(expected))[:3]
            missing = sorted(set(expected) - set(by_rel))[:3]
            raise ArchiveError(f"manifest et contenu divergent (hors manifest : {extra}, manquants : {missing})")
        for rel, f in expected.items():
            info = by_rel[rel]
            if f.get("size") != info.file_size:
                raise ArchiveError(f"taille différente du manifest : {rel!r}")
            h = hashlib.sha256()
            with zf.open(info) as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != f.get("sha256"):
                raise ArchiveError(f"somme SHA-256 incorrecte : {rel!r} (archive altérée ou corrompue)")
    return manifest, by_rel


def _dest(root: Path, rel: str) -> Path:
    """Destination path, refusing anything that would leave the project root through a symlink."""
    real_root = os.path.realpath(root)
    cur = Path(root)
    for part in PurePosixPath(rel).parts:
        cur = cur / part
        if cur.is_symlink():
            raise ArchiveError(f"un lien symbolique bloque l'import : {cur}")
    if not os.path.realpath(cur).startswith(real_root + os.sep):
        raise ArchiveError(f"destination hors du projet : {rel!r}")
    return cur


def _sha_of_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    h = hashlib.sha256()
    with zf.open(info) as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def import_data(archive: Path, root: Path = ROOT, overwrite: bool = False, dry_run: bool = False,
                rebuild: bool = True, now: dt.datetime | None = None, log=print) -> dict:
    """Validate, place the files, then rebuild the database. Returns a summary dict."""
    root = Path(root)
    manifest, by_rel = validate_archive(archive)
    now = now or dt.datetime.now(dt.timezone.utc)
    plan_new, plan_same, plan_conflict = [], [], []
    with zipfile.ZipFile(archive) as zf:
        for rel, info in sorted(by_rel.items()):
            dest = _dest(root, rel)
            if not dest.exists():
                plan_new.append(rel)
            elif _sha256_file(dest) == _sha_of_member(zf, info):
                plan_same.append(rel)
            else:
                plan_conflict.append(rel)
    summary = {"archive": str(archive), "created_at": manifest.get("created_at"),
               "new": len(plan_new), "identical": len(plan_same), "conflicts": len(plan_conflict),
               "files": len(by_rel), "dry_run": dry_run, "backup": None}
    log(f"archive du {manifest.get('created_at')} : {len(by_rel)} fichiers "
        f"({len(plan_new)} nouveaux, {len(plan_same)} identiques, {len(plan_conflict)} différents)")
    if plan_conflict and not overwrite:
        shown = ", ".join(plan_conflict[:5]) + (" …" if len(plan_conflict) > 5 else "")
        raise ImportConflict(f"{len(plan_conflict)} fichier(s) existent déjà avec un contenu différent ({shown}). "
                             "Relance avec --overwrite pour les remplacer (les anciens sont sauvegardés).")
    if dry_run:
        log("  --dry-run : rien n'a été écrit")
        return summary

    backup = root / "data" / f".import-backup-{now.strftime('%Y%m%d-%H%M%S')}"
    with zipfile.ZipFile(archive) as zf:
        for rel in plan_new + plan_conflict:
            dest = _dest(root, rel)
            if dest.exists():
                bpath = backup / rel
                bpath.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, bpath)
                summary["backup"] = str(backup)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".pfa-tmp")
            with zf.open(by_rel[rel]) as src, open(tmp, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            os.chmod(tmp, 0o600)
            os.replace(tmp, dest)
    if overwrite and (root / "data" / "finance.db").exists():
        # rebuild carries transactions over from an existing database; here the archive must win
        bdb = backup / "finance.db"
        bdb.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(root / "data" / "finance.db"), bdb)
        summary["backup"] = str(backup)
    log(f"  {len(plan_new) + len(plan_conflict)} fichier(s) écrit(s)"
        + (f" · anciennes versions sauvegardées dans {backup}" if summary["backup"] else ""))
    if rebuild:
        _run_pfa(root, "rebuild", log=log)
        _run_pfa(root, "export-reference", log=lambda *_: None)
    return summary


def _run_pfa(root: Path, *args: str, log=print) -> None:
    env = {**os.environ, "PFA_ROOT": str(root), "PYTHONPATH": str(Path(__file__).resolve().parent.parent)}
    p = subprocess.run([sys.executable, "-m", "pfa", *args], env=env, cwd=str(Path(__file__).resolve().parent.parent),
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise ArchiveError(f"`pfa {' '.join(args)}` a échoué :\n{p.stdout}\n{p.stderr}")
    for line in p.stdout.strip().splitlines()[-3:]:
        log(f"  {line}")


# --------------------------------------------------------------------------- setup

DIRS = ("data/raw", "data/snapshots", "data/instruments", "data/etf_holdings", "data/companies",
        "data/transactions", "data/logs", "data/generated", "journal/plans", "dashboards", "exports")


def find_archives(root: Path) -> list[Path]:
    """Archives dropped in the project root, in import/, or in exports/ (newest first)."""
    found: list[Path] = []
    for d in (root, root / "import", root / "exports"):
        if d.is_dir():
            found += [p for p in d.glob("pfa-export-*.zip") if p.is_file()]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def create_private_files(root: Path, log=print) -> list[str]:
    """Copy each profile/*.example.* to its private name when that file does not exist yet."""
    made = []
    for ex in sorted((root / "profile").glob("*.example.*")):
        target = ex.with_name(ex.name.replace(".example", ""))
        if not target.exists():
            shutil.copy2(ex, target)
            os.chmod(target, 0o600)
            made.append(target.name)
    if made:
        log(f"  fichiers de profil créés depuis les modèles : {', '.join(made)}")
    return made


def node_ok() -> tuple[bool, str]:
    node = shutil.which("node")
    if not node:
        return False, "Node introuvable (≥ 22.13 requis : `node:sqlite` est intégré)"
    v = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v")
    try:
        major, minor = (int(x) for x in v.split(".")[:2])
    except ValueError:
        return False, f"version de Node illisible : {v!r}"
    if (major, minor) < (22, 13):
        return False, f"Node {v} trop ancien (≥ 22.13 requis)"
    return True, f"Node {v}"


def _yes(answer: str, default: bool) -> bool:
    a = answer.strip().lower()
    return default if not a else a in ("o", "oui", "y", "yes")


def run_setup(root: Path = ROOT, archive: Path | None = None, assume_yes: bool = False,
              build: bool = True, ask=input, log=print) -> int:
    """First-run setup on a fresh clone: folders, data (import or templates), database, web build."""
    root = Path(root)
    log("== Mise en place de personal_finance_agent ==")
    ok, node_msg = node_ok()
    log(f"  Python {sys.version.split()[0]} · {node_msg} · pnpm {'trouvé' if shutil.which('pnpm') else 'INTROUVABLE'}")
    for d in DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)

    # ---- 1. data: import an archive, or start from the templates
    chosen = Path(archive) if archive else None
    if chosen is None and not assume_yes:
        found = find_archives(root)
        if found:
            log("  archive(s) de données trouvée(s) : " + ", ".join(str(p.relative_to(root)) for p in found[:3]))
        if _yes(ask("As-tu une archive de données (.zip) exportée par cette application ? [o/N] "), False):
            if found and _yes(ask(f"Utiliser {found[0].name} ? [O/n] "), True):
                chosen = found[0]
            else:
                p = ask("Chemin de l'archive : ").strip().strip("'\"")
                chosen = Path(p).expanduser() if p else None
    if chosen is not None:
        try:
            import_data(chosen, root, log=log)
        except ImportConflict as e:
            log(f"  ⚠ {e}")
            if assume_yes or not _yes(ask("Remplacer les fichiers existants (sauvegardés) ? [o/N] "), False):
                return 3
            import_data(chosen, root, overwrite=True, log=log)
        except ArchiveError as e:
            log(f"  ✗ archive refusée : {e}")
            return 2
    else:
        create_private_files(root, log=log)
        con = db.connect(root / "data" / "finance.db")
        con.close()
        log("  aucune donnée importée : base vide créée. Remplis profile/ puis lance `python3 -m pfa auth` et `sync`.")
        _run_pfa(root, "export-reference", log=lambda *_: None)

    # ---- 2. web app
    if build and ok and shutil.which("pnpm"):
        if assume_yes or _yes(ask("Installer les dépendances et compiler l'application web (pnpm install && pnpm build) ? [O/n] "), True):
            for cmd in (["pnpm", "install"], ["pnpm", "build"]):
                log(f"  $ {' '.join(cmd)}")
                if subprocess.run(cmd, cwd=str(root)).returncode != 0:
                    log(f"  ✗ `{' '.join(cmd)}` a échoué : relance-le à la main pour voir l'erreur.")
                    return 1
    elif build:
        log("  application web non compilée (Node ≥ 22.13 et pnpm requis ; `corepack enable` fournit pnpm).")

    # ---- 3. git guard against committing private data
    if (root / ".git").is_dir() and (root / ".githooks").is_dir():
        subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=str(root))
        log("  garde-fou de confidentialité activé (hook pre-commit)")

    log("\nPrêt. Suite :")
    if chosen is not None:
        log("  1. python3 -m pfa auth            # connexion Finary à refaire sur cette machine (le jeton n'est pas exporté)")
        log("  2. python3 -m pfa auth-eulerpool --from-env   # clé Eulerpool, si tu enrichis les sociétés")
    else:
        log("  1. édite profile/ (investor_profile.md, account_map.json…), puis python3 -m pfa auth && python3 -m pfa sync")
    log("  → pnpm serve        # http://127.0.0.1:3001")
    return 0
