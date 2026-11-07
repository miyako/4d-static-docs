import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from offline import finalize, verify
from publish import publish, validate_assets
from regenerate import crawl, pack


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "guide").mkdir()
        (self.root / "assets").mkdir()
        (self.root / "guide/CasePage.html").write_text("<p>Content</p>", encoding="utf-8")
        (self.root / "assets/styles.css").write_text("body{color:black}", encoding="utf-8")
        (self.root / "index.html").write_text(
            '<link href="/manual/assets/styles.css">'
            '<a href="http://127.0.0.1:12345/manual/guide/casepage?q=1&amp;x=2#part">Page</a>'
            '<a href="/manual/missing">Missing</a>'
            '<a href="http://localhost:8080/api">Example</a>'
            '<span class="theme-doc-version-badge">Version: example</span>',
            encoding="utf-8",
        )

    def test_case_query_fragment_and_missing_public_fallback(self):
        report = finalize(self.root, "http://127.0.0.1:12345", "https://example.test", "/manual/")
        text = (self.root / "index.html").read_text()
        self.assertIn('href="guide/CasePage.html?q=1&amp;x=2#part"', text)
        self.assertIn('href="https://example.test/manual/missing"', text)
        self.assertIn("http://localhost:8080/api", text)
        self.assertEqual(report["unresolvedUpstreamPaths"], {"/manual/missing": 1})
        audit = verify(self.root, "http://127.0.0.1:12345")
        self.assertEqual(audit["htmlPages"], 2)
        self.assertEqual(audit["versionLabels"]["index.html"], "Version: example")

    def test_ambiguous_casing_is_rejected(self):
        paths = {
            "guide/Page.html": self.root / "guide/Page.html",
            "guide/page.html": self.root / "guide/page.html",
        }
        with patch("offline.inventory", return_value=paths):
            with self.assertRaisesRegex(ValueError, "Ambiguous"):
                finalize(self.root, "http://127.0.0.1:12345", "https://example.test", "/manual/")

    def test_audit_rejects_bad_case_and_missing_css_dependency(self):
        (self.root / "index.html").write_text('<a href="guide/casepage.html">Page</a>')
        (self.root / "assets/styles.css").write_text("body{background:url(missing.png)}")
        with self.assertRaisesRegex(ValueError, "offline reference"):
            verify(self.root)

    def test_source_coverage_and_duplicate_extension_policy(self):
        finalize(self.root, "http://127.0.0.1:12345", "https://example.test", "/manual/")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "missing.html.html").write_text("duplicate")
            verify(self.root, source=source)
            (source / "unlinked.html").write_text("unlinked")
            with self.assertRaisesRegex(ValueError, "published source page absent"):
                verify(self.root, source=source)

    def test_version_badges_are_preserved(self):
        finalize(self.root, "http://127.0.0.1:12345", "https://example.test", "/manual/")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "index.html").write_text(
                '<span class="theme-doc-version-badge">Version: different</span>'
            )
            with self.assertRaisesRegex(ValueError, "published version badge changed"):
                verify(self.root, source=source)


class CrawlTests(unittest.TestCase):
    def test_only_classified_404s_are_tolerated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "wget.log"
            for code, content, valid in (
                (0, "", True),
                (8, "ERROR 404: Not Found.\n", True),
                (8, "ERROR 500: Internal Server Error.\n", False),
                (8, "", False),
                (4, "failed: Connection refused.\n", False),
            ):
                with self.subTest(code=code, content=content):
                    log.write_text(content)
                    with patch("regenerate.subprocess.run", return_value=subprocess.CompletedProcess([], code)) as run:
                        if valid:
                            crawl(["http://127.0.0.1:12345/manual/"], "http://127.0.0.1:12345",
                                  root, log, "/manual/")
                        else:
                            with self.assertRaises(RuntimeError):
                                crawl(["http://127.0.0.1:12345/manual/"], "http://127.0.0.1:12345",
                                      root, log, "/manual/")
                        self.assertIn("--accept-regex=^http://127\\.0\\.0\\.1:12345/manual/", run.call_args.args[0])


class AssetTests(unittest.TestCase):
    def test_archive_contract_checksums_and_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs"
            assets = root / "assets"
            docs.mkdir()
            assets.mkdir()
            (docs / "index.html").write_text("<p>Offline</p>")
            manifest = assets / "snapshot.json"
            manifest.write_text(json.dumps({"syntaxCapture": None, "sourceCommit": "a" * 40}))
            (assets / "link-report.json").write_text("{}")
            pack(docs, manifest, assets)
            snapshot, names = validate_assets(assets)
            self.assertEqual(snapshot["sourceCommit"], "a" * 40)
            self.assertIn("SHA256SUMS", names)
            with zipfile.ZipFile(assets / "docs.zip") as archive:
                self.assertEqual(archive.namelist(), ["snapshot.json", "docs/index.html"])
                self.assertEqual(archive.read("snapshot.json"), manifest.read_bytes())
            (assets / "docs.zip").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                validate_assets(assets)

    def test_publish_refuses_to_overwrite_incomplete_existing_release(self):
        import argparse
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(assets=Path(directory), tag="example", repository="owner/repo",
                                      target="b" * 40, title=None, prerelease=False)
            response = subprocess.CompletedProcess([], 0, json.dumps({"draft": True, "assets": []}), "")
            with patch("publish.validate_assets", return_value=({"sourceCommit": "a" * 40}, ["docs.zip"])):
                with patch("publish.subprocess.run", return_value=response):
                    with self.assertRaisesRegex(ValueError, "incomplete"):
                        publish(args)

    def test_publish_does_not_treat_auth_failure_as_missing_release(self):
        import argparse
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(assets=Path(directory), tag="example", repository="owner/repo",
                                      target="b" * 40, title=None, prerelease=False)
            response = subprocess.CompletedProcess([], 1, "", "gh: HTTP 403: Forbidden")
            with patch("publish.validate_assets", return_value=({"sourceCommit": "a" * 40}, ["docs.zip"])):
                with patch("publish.subprocess.run", return_value=response) as run:
                    with self.assertRaisesRegex(RuntimeError, "403"):
                        publish(args)
                    self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
