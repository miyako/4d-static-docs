from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "pipeline"))

import extract_review_bundle as bundle


class ReviewBundleTests(unittest.TestCase):
    def test_changes_include_removals_and_unchanged(self):
        self.assertEqual(
            bundle.changes({"A": "old", "B": "same", "C": "removed"},
                           {"A": "new", "B": "same", "D": "added"}),
            {"added": ["D"], "removed": ["C"], "changed": ["A"], "unchanged": ["B"]},
        )

    def test_sections_include_html_only_members(self):
        pages = {"Collection": {"sections": [{"headingKey": ".newMember()", "summary": "new"}]}}
        self.assertEqual(list(bundle.sections(pages)), ["Collection:.newMember()"])

    def test_paths_cannot_escape_repository(self):
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            bundle.inside_repo(REPO, "../outside")

    def run_fixture(self, parent: Path, output_name: str, syntax: str = ".length : Integer"):
        docs = parent / "docs" / "22"
        (docs / "commands").mkdir(parents=True, exist_ok=True)
        (docs / "API").mkdir(exist_ok=True)
        (docs / "commands" / "abs.html").write_text(
            '<article><div class="markdown"><header><h1>Abs</h1></header>'
            '<p><strong>Abs</strong> ( number ) -&gt; Real</p>'
            '<h2>Description</h2><p>Version: 22</p><p>Absolute value.</p></div></article>',
            encoding="utf-8",
        )
        (docs / "API" / "CollectionClass.html").write_text(
            '<article><div class="markdown"><header><h1>Collection</h1></header>'
            '<h2>.length</h2><p>.length : Integer</p><p>Number of elements.</p>'
            '<h2>.newMember()</h2><p>.newMember() : Text</p><p>HTML-only member.</p>'
            '</div></article>', encoding="utf-8",
        )
        syntax_path = parent / "syntax.json"
        syntax_path.write_text(json.dumps({"Collection": {"length": {"Syntax": syntax}}}),
                               encoding="utf-8")
        output = parent / output_name
        argv = [
            "extract_review_bundle.py", "--repo-root", str(REPO),
            "--docs-tree", str(parent / "docs"), "--syntax-json", str(syntax_path),
            "--output", str(output),
        ]
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            result = bundle.main()
        return result, output

    def test_end_to_end_isolated_repeatable_and_preserves_html_only_members(self):
        # Keep source fixtures under the worktree, as required by the entry point.
        (REPO / "extraction").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=REPO / "extraction") as directory:
            parent = Path(directory)
            baseline_paths = [
                REPO / "out/manifest.json", REPO / "out/oop_manifest.json",
                REPO / "out/oop_stage1_raw.json", REPO / "out/4d-command-ir.json",
                REPO / "out/4d-oop-ir.json", REPO / "out/stage3_progress.json",
            ]
            before = {path: path.read_bytes() for path in baseline_paths}
            result, output = self.run_fixture(parent, "first")
            self.assertEqual(result, 0)
            provenance = bundle.read_json(output / "provenance.json")
            self.assertEqual(provenance["status"], "extracted_review_required")
            self.assertFalse(provenance["syntaxSource"]["matchesDocsVersion"])
            self.assertEqual(len(provenance["stages"]), 8)
            self.assertEqual(bundle.read_json(output / "manifest.json")["counts"]["inScope"], 1)
            self.assertIn("Collection:.newMember()",
                          bundle.read_json(output / "oop_section_changes.json")["added"])
            self.assertEqual(bundle.read_json(output / "oop_source_diff.json")["counts"]["syntaxen_missing"], 1)
            self.assertNotIn("Collection.newMember", bundle.read_json(output / "oop_signatures.json"))
            self.assertFalse((output / "4d-command-ir.json").exists())
            self.assertFalse((output / "4d-oop-ir.json").exists())
            result, second = self.run_fixture(parent, "second")
            self.assertEqual(result, 0)
            for path in output.glob("*.json"):
                self.assertEqual(bundle.read_json(path), bundle.read_json(second / path.name), path.name)
            for path, content in before.items():
                self.assertEqual(path.read_bytes(), content, str(path))
            with self.assertRaises(FileExistsError):
                self.run_fixture(parent, "first")

    def test_failed_signature_gate_keeps_diagnostics_without_success_status(self):
        (REPO / "extraction").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=REPO / "extraction") as directory:
            result, output = self.run_fixture(Path(directory), "failed", ".length : ???")
            self.assertEqual(result, 1)
            provenance = bundle.read_json(output / "provenance.json")
            self.assertEqual(provenance["status"], "failed")
            self.assertIn("stage2_signatures.py failed", provenance["error"])
            self.assertFalse(bundle.read_json(output / "oop_roundtrip_report.json")["passed"])
            self.assertTrue((output / "logs/stage2_signatures_oop.log").exists())
            self.assertFalse((output / "oop_param_conflicts.json").exists())
            self.assertIn("**failed**", (output / "summary.md").read_text())

    def test_classic_partial_output_is_a_failure(self):
        real_run = bundle.subprocess.run

        def incomplete(command, **kwargs):
            result = real_run(command, **kwargs)
            if any(str(value).endswith("/stage1_extract.py") for value in command) and not any(
                "/oop/" in str(value) for value in command
            ):
                path = REPO / command[command.index("--out") + 1]
                raw = bundle.read_json(path)
                raw["records"] = []
                raw["failures"] = [{"id": "Abs", "error": "test extraction failure"}]
                bundle.write_json(path, raw)
            return result

        (REPO / "extraction").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=REPO / "extraction") as directory, \
                patch.object(bundle.subprocess, "run", side_effect=incomplete):
            result, output = self.run_fixture(Path(directory), "partial")
            self.assertEqual(result, 1)
            self.assertIn("classic extraction is incomplete",
                          bundle.read_json(output / "provenance.json")["error"])
            self.assertFalse((output / "candidates.json").exists())


if __name__ == "__main__":
    unittest.main()
