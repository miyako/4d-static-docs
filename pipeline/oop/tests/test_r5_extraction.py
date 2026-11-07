import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stage7_doc_examples import _code_lines
from check_schema_gate import verbatim_syntax_violations
import stage9_hover_crosscheck as hover_check
from review_refresh import conflict_inventory


class R5ExtractionTests(unittest.TestCase):
    def test_div_and_span_token_lines_preserve_source(self):
        for tag in ("div", "span"):
            with self.subTest(tag=tag):
                html = (
                    f'<pre><code><{tag} class="token-line">var $x : Text<br/></{tag}>'
                    f'<{tag} class="token-line"><span>  $x:="hello"</span><br/></{tag}>'
                    f'<{tag} class="token-line"><br/></{tag}></code></pre>'
                )
                self.assertEqual(
                    _code_lines(BeautifulSoup(html, "html.parser").pre),
                    ["var $x : Text", '  $x:="hello"'],
                )

    def test_plain_code_lines(self):
        block = BeautifulSoup("<pre><code>a\n  b\n</code></pre>", "html.parser").pre
        self.assertEqual(_code_lines(block), ["a", "  b"])

    def test_missing_source_member_fails_invariant(self):
        doc = {"commands": [{"id": "Missing.property", "kind": "oop_property"}]}
        self.assertEqual(len(verbatim_syntax_violations(doc, {})), 1)

    def test_hover_attaches_from_oop_project_directory(self):
        with patch("stage9_hover_crosscheck.subprocess.run") as run:
            run.return_value = SimpleNamespace(
                returncode=0, stdout='{"result": ".length : Integer"}', stderr=""
            )
            path = hover_check.PROJECT_DIR / "Sources/Methods/SynthOOP_Vector_length.4dm"
            self.assertEqual(hover_check.hover(path, 0, 5), ".length : Integer")
            self.assertEqual(run.call_args.kwargs["cwd"], hover_check.PROJECT_DIR)
            self.assertIn(str(path), run.call_args.args[0])

    def test_unreviewed_conflict_fails_inventory(self):
        current = {"items": [{"id": "New.member", "kind": "type_mismatch"}]}
        with self.assertRaisesRegex(SystemExit, "Unreviewed OOP conflicts"):
            conflict_inventory(current, {"items": []})


if __name__ == "__main__":
    unittest.main()
