"""Export / import of the user's data: round trip, safety against hostile archives, overwrite policy.

The archive is untrusted input, so most of this file is about what must be REFUSED.
Run: python3 -m unittest discover tests
"""
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))

from pfa import db, portability as pt  # noqa: E402


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def make_zip(path: Path, entries: dict[str, bytes], manifest: dict | None = None, listed: dict[str, bytes] | None = None):
    """Build an archive. `entries` are the files under files/ ; the manifest lists them unless overridden."""
    listed = entries if listed is None else listed
    m = {"format": pt.FORMAT, "format_version": pt.FORMAT_VERSION, "created_at": "2026-01-01T00:00:00+00:00",
         "files": [{"path": k, "sha256": sha(v), "size": len(v)} for k, v in listed.items()]}
    m.update(manifest or {})
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(pt.MANIFEST, json.dumps(m))
        for k, v in entries.items():
            zf.writestr(f"files/{k}" if not k.startswith(("../", "/")) else f"files/{k}", v)
    return path


def populate(root: Path):
    """A small but complete project tree, built with the real pipeline."""
    env = {**os.environ, "PFA_ROOT": str(root), "PYTHONPATH": str(PROJECT)}
    shutil.copytree(PROJECT / "reference", root / "reference")
    (root / "profile").mkdir(parents=True, exist_ok=True)
    for name, doc in (("targets.json", {"asset_class": {"equity": 1.0}}), ("manual_inputs.json", {}),
                      ("account_map.json", {"accounts": {}}), ("flow_rules.json", {"rules": []})):
        (root / "profile" / name).write_text(json.dumps(doc))
    (root / "profile" / "investor_profile.md").write_text("# profil de test\n")
    sh = lambda *a: subprocess.run([sys.executable, "-m", "pfa", *a], env=env, cwd=PROJECT,  # noqa: E731
                                   capture_output=True, text=True, check=True)
    sh("load-snapshot", str(HERE / "fixtures/sample_snapshot_2.json"))
    sh("load-instrument", str(HERE / "fixtures/instrument_FR0011871128.json"))
    code = ("from pfa import db, runs\n"
            "con = db.connect()\n"
            "r = runs.new('transactions'); db.upsert_run(con, {**r, 'status': 'ok'})\n"
            "db.load_transactions(con, [{'id': 't1', 'date': '2026-01-02', 'label': 'Vir Acme Corp', 'account': 'A',"
            " 'amount': 3500.0, 'flow': 'income', 'source': 'bankin-csv', 'category': 'Incomes',"
            " 'subcategory': 'Salaries', 'rule_id': 'salary-acme', 'note': None, 'period_month': None,"
            " 'account_id': None}], r['run_id'])\n")
    subprocess.run([sys.executable, "-c", code], env=env, cwd=PROJECT, check=True)
    (root / "journal").mkdir(exist_ok=True)
    (root / "journal" / "2026-01-01-note.md").write_text("une analyse\n")
    (root / "data" / "raw" / "2026-01-01").mkdir(parents=True)
    (root / "data" / "raw" / "2026-01-01" / "x.json").write_text("{}")
    (root / "data" / "transactions").mkdir(exist_ok=True)
    (root / "data" / "transactions" / "export_é.csv").write_text("a;b\n")
    # things that must NEVER travel
    (root / "data" / "oauth_client.json").write_text('{"client_id": "x"}')
    (root / "data" / "generated").mkdir(exist_ok=True)
    (root / "data" / "generated" / "rules.json").write_text("{}")
    (root / "data" / "instruments" / "_build_helper.py").write_text("print('x')")
    (root / "data" / "logs").mkdir(exist_ok=True)
    (root / "data" / "logs" / "sync.log").write_text("log")
    (root / ".env").write_text("EULERPOOL_API_KEY=secret")


class RoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.a, self.b = Path(self.tmp.name) / "a", Path(self.tmp.name) / "b"
        self.a.mkdir(), self.b.mkdir()
        populate(self.a)
        self.logs = []
        self.log = self.logs.append

    def tearDown(self):
        self.tmp.cleanup()

    def test_export_holds_sources_of_truth_and_no_secrets(self):
        z = pt.export_data(self.a, log=self.log)
        with zipfile.ZipFile(z) as zf:
            names = set(zf.namelist())
            m = json.loads(zf.read("manifest.json"))
        listed = {f["path"] for f in m["files"]}
        for must in ("profile/investor_profile.md", "profile/targets.json", "data/transactions.jsonl",
                     "data/snapshots/2026-10-01.json", "data/instruments/FR0011871128.json",
                     "journal/2026-01-01-note.md", "data/raw/2026-01-01/x.json", "data/transactions/export_é.csv"):
            self.assertIn(must, listed, must)
        blob = " ".join(names)
        for never in ("finance.db", "oauth_client", ".env", "generated", "sync.log", "_build_helper"):
            self.assertNotIn(never, blob, never)
        self.assertEqual(stat.S_IMODE(z.stat().st_mode), 0o600)            # the archive itself is private
        self.assertEqual(m["transactions"], 1)

    def test_no_raw_leaves_the_provenance_archive_out(self):
        z = pt.export_data(self.a, include_raw=False, log=self.log)
        with zipfile.ZipFile(z) as zf:
            self.assertFalse(any("data/raw" in n for n in zf.namelist()))

    def test_round_trip_restores_files_database_and_transactions(self):
        z = pt.export_data(self.a, log=self.log)
        s = pt.import_data(z, self.b, log=self.log)
        self.assertEqual(s["conflicts"], 0)
        # the files are byte-identical
        for rel in ("profile/investor_profile.md", "data/snapshots/2026-10-01.json", "journal/2026-01-01-note.md",
                    "data/transactions/export_é.csv"):
            self.assertEqual((self.a / rel).read_bytes(), (self.b / rel).read_bytes(), rel)
        # the database was rebuilt from them, including the transaction and its stored classification
        con = db.connect(self.b / "data" / "finance.db")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)
        row = con.execute("SELECT flow, rule_id, amount FROM transactions WHERE id='t1'").fetchone()
        self.assertEqual((row["flow"], row["rule_id"], row["amount"]), ("income", "salary-acme", 3500.0))
        self.assertEqual(stat.S_IMODE((self.b / "profile" / "investor_profile.md").stat().st_mode), 0o600)
        # re-importing the same archive is a no-op, not a conflict
        again = pt.import_data(z, self.b, rebuild=False, log=self.log)
        self.assertEqual((again["new"], again["conflicts"]), (0, 0))

    def test_rebuild_alone_restores_transactions_from_the_portable_file(self):
        pt.export_data(self.a, log=self.log)                                 # writes data/transactions.jsonl
        (self.a / "data" / "finance.db").unlink()
        pt._run_pfa(self.a, "rebuild", log=self.log)
        con = db.connect(self.a / "data" / "finance.db")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 1)

    def test_dry_run_writes_nothing(self):
        z = pt.export_data(self.a, log=self.log)
        s = pt.import_data(z, self.b, dry_run=True, log=self.log)
        self.assertGreater(s["new"], 0)
        self.assertFalse((self.b / "data").exists())

    def test_different_existing_files_block_the_import_unless_overwritten(self):
        z = pt.export_data(self.a, log=self.log)
        pt.import_data(z, self.b, rebuild=False, log=self.log)
        (self.b / "profile" / "investor_profile.md").write_text("# modifié ici\n")
        with self.assertRaises(pt.ImportConflict):
            pt.import_data(z, self.b, rebuild=False, log=self.log)
        self.assertEqual((self.b / "profile" / "investor_profile.md").read_text(), "# modifié ici\n")
        s = pt.import_data(z, self.b, overwrite=True, rebuild=False, log=self.log)
        self.assertEqual((self.b / "profile" / "investor_profile.md").read_text(), "# profil de test\n")
        saved = list(Path(s["backup"]).rglob("investor_profile.md"))
        self.assertEqual(saved[0].read_text(), "# modifié ici\n")             # the old version is not lost


class Hostile(unittest.TestCase):
    """Every one of these must be refused, and refuse BEFORE writing a single file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        self.root.mkdir()
        self.z = Path(self.tmp.name) / "a.zip"

    def tearDown(self):
        self.tmp.cleanup()

    def refuse(self, msg_part=None):
        with self.assertRaises(pt.ArchiveError) as cm:
            pt.import_data(self.z, self.root, rebuild=False, log=lambda *_: None)
        self.assertEqual(list(self.root.iterdir()), [], "nothing may be written")
        if msg_part:
            self.assertIn(msg_part, str(cm.exception))

    def test_path_traversal(self):
        make_zip(self.z, {"../evil.txt": b"x"})
        self.refuse()

    def test_dotdot_inside_the_path(self):
        make_zip(self.z, {"journal/../../evil.txt": b"x"})
        self.refuse()

    def test_absolute_path(self):
        with zipfile.ZipFile(self.z, "w") as zf:
            zf.writestr(pt.MANIFEST, json.dumps({"format": pt.FORMAT, "format_version": 1, "files": []}))
            zf.writestr("/etc/evil", b"x")
        self.refuse("hors de files/")

    def test_backslash_separator(self):
        make_zip(self.z, {"journal\\..\\evil": b"x"})
        self.refuse()

    def test_destination_outside_the_whitelist(self):
        for bad in ("data/finance.db", "pfa/cli.py", ".github/workflows/x.yml", "profile/evil.sh",
                    "data/instruments/_x.json", "apps/server/main.js", "profile/sub/targets.json"):
            make_zip(self.z, {bad: b"x"})
            self.refuse("non autorisée")

    def test_symlink_member(self):
        with zipfile.ZipFile(self.z, "w") as zf:
            zf.writestr(pt.MANIFEST, json.dumps({"format": pt.FORMAT, "format_version": 1, "files": [
                {"path": "journal/link", "sha256": sha(b"/etc/passwd"), "size": 11}]}))
            info = zipfile.ZipInfo("files/journal/link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, b"/etc/passwd")
        self.refuse("symbolique")

    def test_unlisted_extra_file(self):
        make_zip(self.z, {"journal/a.md": b"a", "journal/extra.md": b"b"},
                 listed={"journal/a.md": b"a"})
        self.refuse("divergent")

    def test_listed_but_missing_file(self):
        make_zip(self.z, {"journal/a.md": b"a"}, listed={"journal/a.md": b"a", "journal/b.md": b"b"})
        self.refuse("divergent")

    def test_tampered_content_fails_the_checksum(self):
        make_zip(self.z, {"journal/a.md": b"tampered"}, listed={"journal/a.md": b"original"})
        # same length so only the hash can catch it
        self.refuse("SHA-256")

    def test_size_mismatch(self):
        make_zip(self.z, {"journal/a.md": b"abc"})
        m = json.loads(zipfile.ZipFile(self.z).read(pt.MANIFEST))
        m["files"][0]["size"] = 99
        make_zip(self.z, {"journal/a.md": b"abc"}, manifest={"files": m["files"]})
        self.refuse("taille")

    def test_newer_format_is_refused_with_advice(self):
        make_zip(self.z, {"journal/a.md": b"a"}, manifest={"format_version": 999})
        self.refuse("mets l'application à jour")

    def test_wrong_format_and_missing_manifest_and_not_a_zip(self):
        make_zip(self.z, {"journal/a.md": b"a"}, manifest={"format": "autre-chose"})
        self.refuse("format inattendu")
        with zipfile.ZipFile(self.z, "w") as zf:
            zf.writestr("files/journal/a.md", b"a")
        self.refuse("manifest.json absent")
        self.z.write_bytes(b"not a zip at all")
        self.refuse("pas une archive zip")

    def test_a_symlinked_destination_cannot_escape_the_project(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (self.root / "journal").symlink_to(outside)                           # journal/ -> elsewhere
        make_zip(self.z, {"journal/a.md": b"a"})
        with self.assertRaises(pt.ArchiveError):
            pt.import_data(self.z, self.root, rebuild=False, log=lambda *_: None)
        self.assertEqual(list(outside.iterdir()), [])


class Setup(unittest.TestCase):
    def test_setup_without_data_creates_folders_private_files_and_an_empty_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(PROJECT / "reference", root / "reference")
            (root / "profile").mkdir()
            (root / "profile" / "targets.example.json").write_text('{"asset_class": {}}')
            (root / "profile" / "manual_inputs.example.json").write_text("{}")
            rc = pt.run_setup(root, assume_yes=True, build=False, log=lambda *_: None)
            self.assertEqual(rc, 0)
            self.assertTrue((root / "profile" / "targets.json").exists())
            self.assertTrue((root / "data" / "finance.db").exists())
            self.assertTrue((root / "journal" / "plans").is_dir())

    def test_setup_with_an_archive_imports_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "src", Path(tmp) / "dst"
            src.mkdir(), dst.mkdir()
            populate(src)
            z = pt.export_data(src, log=lambda *_: None)
            shutil.copytree(PROJECT / "reference", dst / "reference")
            rc = pt.run_setup(dst, archive=z, assume_yes=True, build=False, log=lambda *_: None)
            self.assertEqual(rc, 0)
            con = db.connect(dst / "data" / "finance.db")
            self.assertEqual(con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 1)

    def test_setup_asks_and_finds_an_archive_dropped_in_the_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "src", Path(tmp) / "dst"
            src.mkdir(), dst.mkdir()
            populate(src)
            pt.export_data(src, out=dst / "pfa-export-20260101-000000.zip", log=lambda *_: None)
            shutil.copytree(PROJECT / "reference", dst / "reference")
            answers = iter(["o", ""])                       # "have an archive?" yes ; "use this one?" default yes
            rc = pt.run_setup(dst, ask=lambda _q: next(answers), build=False, log=lambda *_: None)
            self.assertEqual(rc, 0)
            self.assertTrue((dst / "data" / "snapshots" / "2026-10-01.json").exists())


if __name__ == "__main__":
    unittest.main()
