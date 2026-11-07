from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))
from review_classic_refresh import normalize
from stage6_hover_crosscheck import classify
import stage6_synth_examples as synth
import record_r5_snapshot as snapshot


class R5ClassicTests(unittest.TestCase):
    def test_snapshot_requires_current_hash_bound_classic_evidence(self):
        evidence = snapshot.classic_evidence()
        self.assertEqual(evidence["methods"], 1338)
        self.assertEqual(evidence["blocks"], 2563)
        original = snapshot.digest
        with patch.object(snapshot, "digest", side_effect=lambda path:
                          "stale" if path == "out/lsp_crosscheck_report.json" else original(path)):
            with self.assertRaisesRegex(ValueError, "Stale classic"):
                snapshot.classic_evidence()

    def run_compiler_case(self, entries):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "Project/Sources/Methods/Demo.4dm"
            source.parent.mkdir(parents=True)
            source.write_text("var $value : Integer\n\n// overload\n$value:=1\n")
            manifest_path = root / "manifest.json"
            manifest_path.write_text("{}")
            ir_path = root / "ir.json"
            ir_path.write_text("{}")
            bridge = root / "bridge"
            bridge.write_text("test bridge")
            compiler = root / "compiler"
            compiler.write_text("test compiler")
            manifest = {"pilot_ids": ["Demo"], "files": {
                "Sources/Methods/Demo.4dm": {"command_id": "Demo",
                                           "overloads": [{"overload_index": 0, "comment_line": 3}]}
            }}
            with patch.multiple(synth, ROOT=root, MANIFEST_PATH=manifest_path,
                                IR_PATH=ir_path, REPORT_PATH=root / "report.json",
                                TOOL4D_LSP=bridge), \
                    patch.object(synth, "load_json", side_effect=[{"commands": [{"id": "Demo"}]}, manifest]), \
                    patch.object(synth, "resolve_target_ids", return_value=(["Demo"], [])), \
                    patch.dict(os.environ, {"TOOL4D_PATH": str(compiler)}), \
                    patch.object(synth.subprocess, "check_output", return_value="21 R5 build 21R5.100156"), \
                    patch.object(synth.subprocess, "run", return_value=SimpleNamespace(
                        returncode=1, stdout=json.dumps(entries), stderr="")):
                (root / "out").mkdir()
                with self.assertRaises(SystemExit) as error:
                    synth.cmd_validate(SimpleNamespace())
                return error.exception, json.loads((root / "report.json").read_text()) if (root / "report.json").exists() else None

    def test_compiler_missing_file_is_unverified_not_clean(self):
        error, report = self.run_compiler_case([])
        self.assertIn("omitted targeted files", str(error))
        self.assertIsNone(report)

    def test_compiler_setup_diagnostic_is_not_silently_dropped(self):
        error, report = self.run_compiler_case([{
            "uri": "file:///test/Project/Sources/Methods/Demo.4dm",
            "diagnostics": [{"severity": 1, "message": "Invalid setup",
                             "range": {"start": {"line": 0}, "end": {"line": 0}}}]
        }])
        self.assertEqual(error.code, 1)
        self.assertEqual(report[0]["status"], "error")
        self.assertEqual(report[0]["diagnostics"][0]["message"], "Invalid setup")

    def test_hover_gap_requires_clean_compiler_evidence_and_known_delimiter(self):
        gap = "No hover information available at this position."
        clean = [{"id": "Begin-SQL", "status": "clean", "diagnostics": []}]
        self.assertEqual(classify("Begin-SQL", "Begin SQL", gap, clean), "explained_no_hover")
        self.assertEqual(classify("Begin-SQL", "Begin SQL", gap, []), "unrecognized")
        self.assertEqual(classify("Fabricated", "Fabricated", gap, clean), "unrecognized")
        self.assertEqual(classify("Begin-SQL", "Begin SQL", "**Other command**", clean), "unrecognized")
    def test_normalization_retains_substantive_prose_and_signature_deltas(self):
        before = {"contentHash": "old", "versionBadge": "R3", "sections": {"text": "same\u200b text"},
                  "signatureLines": [{"text": "call(a)", "html": "<p>old</p>"}]}
        after = {"contentHash": "new", "versionBadge": "R5", "sections": {"text": "same text"},
                 "signatureLines": [{"text": "call(a)", "html": "<p>new</p>"}]}
        self.assertEqual(normalize(before), normalize(after))
        after["signatureLines"][0]["text"] = "call(a;b)"
        self.assertNotEqual(normalize(before), normalize(after))
        after["signatureLines"][0]["text"] = "call(a)"
        after["sections"]["text"] = "different text"
        self.assertNotEqual(normalize(before), normalize(after))

    def test_assembled_r5_exact_api_shapes_and_coverage(self):
        ir = json.loads((ROOT / "out/4d-command-ir.json").read_text())
        commands = {c["id"]: c for c in ir["commands"]}
        manifest = json.loads((ROOT / "out/manifest.json").read_text())
        self.assertEqual(set(commands), {e["id"] for e in manifest["entries"]})
        for cid in ("defer", "Deferred-formulas"):
            self.assertEqual(commands[cid]["sinceVersion"], "21 R4")
        for cid in ("OBJECT-Get-padding", "OBJECT-SET-PADDING"):
            self.assertEqual(commands[cid]["sinceVersion"], "21 R5")
        self.assertEqual(commands["Deferred-formulas"]["overloads"][0]["returns"]["name"], "Collection")
        for cid, direction in (("OBJECT-GET-RGB-COLORS", "out"), ("OBJECT-SET-RGB-COLORS", "in")):
            params = commands[cid]["overloads"][0]["params"]
            border = next(p for p in params if p["name"] == "borderColor")
            self.assertTrue(border["optional"])
            self.assertEqual(border["direction"], direction)
            self.assertEqual({t["name"] for t in border["type"]}, {"Text", "Integer"})
        for cid, parameter in (("CREATE-INDEX", "indexType"), ("SET-INDEX", "index")):
            param = next(p for p in commands[cid]["overloads"][0]["params"] if p["name"] == parameter)
            self.assertTrue({4, 5, 6} <= {v["value"] for v in param["sentinelValues"]})
        self.assertEqual({v["value"] for v in ir["enums"]["FormObjectBorderStyle"]["values"]},
                         {0, 1, 2, 3, 4, 5, 6, 8, 9})
        self.assertTrue(any("REST process" in c for c in commands["Session"]["constraints"]))

    def test_synthetic_manifest_covers_every_non_view_pro_command(self):
        ir = json.loads((ROOT / "out/4d-command-ir.json").read_text())
        expected = {c["id"] for c in ir["commands"] if c["theme"] != "4D-View-Pro"}
        manifest = json.loads((ROOT / "out/synth_manifest.json").read_text())
        self.assertEqual(expected, {entry["command_id"] for entry in manifest["files"].values()})
        for path in manifest["files"]:
            self.assertTrue((ROOT / "Project" / path).is_file(), path)
        verdicts = json.loads((ROOT / "out/lsp_crosscheck_report.json").read_text())
        self.assertEqual(expected, {v["id"] for v in verdicts})
        self.assertTrue(all(v["status"] == "clean" and not v["diagnostics"] for v in verdicts))


if __name__ == "__main__":
    unittest.main()
