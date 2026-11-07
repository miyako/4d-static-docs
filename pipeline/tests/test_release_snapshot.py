from __future__ import annotations

import contextlib
import io
import hashlib
import json
import shutil
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "pipeline"))
import extract_review_bundle as bundle
import release_snapshot as release


class ReleaseSnapshotTests(unittest.TestCase):
    def assets(self, root: Path, *, bundled=True, extra=None, label_bytes=0):
        root.mkdir()
        capture = b'{"Collection":{"length":{"Syntax":".length : Integer"}}}'
        manifest = {
            "schemaVersion": 1, "archiveRoot": "docs", "sourceRepository": "4d/docs",
            "sourceCommit": "a" * 40, "generatorCommit": "b" * 40, "htmlPages": 2,
            "versionLabels": {"page-labels": "x" * label_bytes},
            "syntaxCapture": {
                "asset": "syntaxEN.json", "version": "21-R4", "build": "test.R4",
                "sha256": hashlib.sha256(capture).hexdigest(),
            } if bundled else None,
        }
        bundle.write_json(root / "snapshot.json", manifest)
        bundle.write_json(root / "link-report.json", {})
        if bundled:
            (root / "syntaxEN.json").write_bytes(capture)
        with zipfile.ZipFile(root / "docs.zip", "w") as archive:
            archive.write(root / "snapshot.json", "snapshot.json")
            archive.writestr(
                "docs/21-R4/commands/abs.html",
                '<article><div class="markdown"><header><h1>Abs</h1></header>'
                '<p><strong>Abs</strong> ( value ) -&gt; Real</p></div></article>',
            )
            archive.writestr(
                "docs/21-R4/API/CollectionClass.html",
                '<article><div class="markdown"><h1>Collection</h1>'
                '<h2>.length</h2><p>.length : Integer</p></div></article>',
            )
            if extra:
                archive.writestr(*extra)
        self.checksums(root)
        return manifest

    def checksums(self, root):
        (root / "SHA256SUMS").write_text("".join(
            f"{release.sha256(path)}  {path.name}\n"
            for path in sorted(root.iterdir()) if path.name != "SHA256SUMS"
        ))

    def test_verified_archive_and_bundled_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.assets(root / "assets")
            hashes = release.verify_assets(root / "assets")
            release.validate_manifest(manifest, hashes)
            release.unpack(root / "assets", root / "site", manifest)
            self.assertTrue((root / "site/docs/21-R4/API/CollectionClass.html").exists())

    def test_full_snapshot_manifest_larger_than_one_megabyte(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.assets(root / "assets", label_bytes=2_200_000)
            hashes = release.verify_assets(root / "assets")
            release.validate_manifest(manifest, hashes)
            release.unpack(root / "assets", root / "site", manifest)
            self.assertGreater((root / "site/snapshot.json").stat().st_size, 1024 * 1024)

    def test_corrupted_asset_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            assets = Path(temp) / "assets"
            self.assets(assets)
            (assets / "docs.zip").write_bytes(b"corrupted")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                release.verify_assets(assets)

    def test_unsafe_zip_entries_are_rejected_before_writing(self):
        link = zipfile.ZipInfo("docs/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for entry in ("docs/../../escape", "/docs/escape", "docs\\escape", link):
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                manifest = self.assets(root / "assets", extra=(entry, "bad"))
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    release.unpack(root / "assets", root / "site", manifest)
                self.assertFalse((root / "site").exists())

    def test_different_embedded_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.assets(root / "assets")
            manifest["sourceCommit"] = "c" * 40
            bundle.write_json(root / "assets/snapshot.json", manifest)
            self.checksums(root / "assets")
            release.validate_manifest(manifest, release.verify_assets(root / "assets"))
            with self.assertRaisesRegex(ValueError, "manifests differ"):
                release.unpack(root / "assets", root / "site", manifest)

    def test_archive_count_and_file_directory_conflicts(self):
        for conflict in (False, True):
            with self.subTest(conflict=conflict), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                manifest = self.assets(root / "assets")
                if conflict:
                    with zipfile.ZipFile(root / "assets/docs.zip", "a") as archive:
                        archive.writestr("docs/file", "file")
                        archive.writestr("docs/file/child", "child")
                else:
                    manifest["htmlPages"] = 3
                    bundle.write_json(root / "assets/snapshot.json", manifest)
                    # Keep both manifests identical while testing the HTML count.
                    with zipfile.ZipFile(root / "assets/docs.zip", "w") as archive:
                        archive.write(root / "assets/snapshot.json", "snapshot.json")
                        archive.writestr("docs/page.html", "one page")
                with self.assertRaisesRegex(ValueError, "conflict|HTML count"):
                    release.unpack(root / "assets", root / "site", manifest)
                self.assertFalse((root / "site").exists())

    def test_no_capture_and_capture_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = self.assets(root / "assets", bundled=False)
            hashes = release.verify_assets(root / "assets")
            release.validate_manifest(manifest, hashes)
            manifest["syntaxCapture"] = {
                "asset": "syntaxEN.json", "version": "21-R4", "build": "test",
                "sha256": "a" * 64,
            }
            with self.assertRaisesRegex(ValueError, "capture hash"):
                release.validate_manifest(manifest, hashes)

    def run_release(self, parent, *, bundled=True, override=False):
        assets = parent / "producer"
        self.assets(assets, bundled=bundled)
        metadata = {"tagName": "pinned-test", "url": "https://github.com/test/docs/releases/tag/pinned-test",
                    "assets": [{"name": path.name} for path in assets.iterdir()]}
        real_run = bundle.subprocess.run
        real_output = bundle.subprocess.check_output

        def gh_run(command, **kwargs):
            if command[:3] == ["gh", "release", "download"]:
                shutil.copytree(assets, Path(command[command.index("--dir") + 1]), dirs_exist_ok=True)
                return bundle.subprocess.CompletedProcess(command, 0)
            return real_run(command, **kwargs)

        def gh_output(command, **kwargs):
            if command[:3] == ["gh", "release", "view"]:
                return json.dumps(metadata)
            return real_output(command, **kwargs)

        output = parent / "review"
        source = parent / "source"
        argv = ["extract_review_bundle.py", "--release-tag", "pinned-test",
                "--release-repo", "test/docs", "--version", "21-R4",
                "--release-source", str(source), "--output", str(output)]
        if override:
            argv += ["--syntax-version", "bad"]
        with patch.object(sys, "argv", argv), \
                patch.object(bundle.subprocess, "run", side_effect=gh_run), \
                patch.object(bundle.subprocess, "check_output", side_effect=gh_output), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = bundle.main()
        return result, output

    def test_release_entrypoint_records_actual_provenance(self):
        (REPO / "extraction").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=REPO / "extraction") as temp:
            result, output = self.run_release(Path(temp))
            self.assertEqual(result, 0)
            provenance = bundle.read_json(output / "provenance.json")
            self.assertIsNone(provenance["staticSnapshotCommit"])
            self.assertEqual(provenance["staticSnapshot"]["sourceCommit"], "a" * 40)
            self.assertEqual(provenance["syntaxSource"]["build"], "test.R4")
            self.assertEqual(provenance["syntaxSource"]["declaredDocsVersion"], "21-R4")
            self.assertTrue(provenance["syntaxSource"]["matchesDocsVersion"])
            self.assertIn("docs.zip", provenance["release"]["sha256"])
            self.assertTrue((output / "snapshot.json").exists())

    def test_release_without_capture_requires_explicit_external_capture(self):
        (REPO / "extraction").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=REPO / "extraction") as temp:
            result, output = self.run_release(Path(temp), bundled=False)
            self.assertEqual(result, 1)
            self.assertIn("no syntax capture", bundle.read_json(output / "provenance.json")["error"])

    def test_bundled_capture_cannot_be_relabelled(self):
        (REPO / "extraction").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=REPO / "extraction") as temp:
            result, output = self.run_release(Path(temp), override=True)
            self.assertEqual(result, 1)
            self.assertIn("must not be overridden", bundle.read_json(output / "provenance.json")["error"])


if __name__ == "__main__":
    unittest.main()
