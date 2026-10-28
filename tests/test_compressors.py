"""Testes dos compressores, do registry e do middleware. Rode com:

    python3 -m unittest discover -s tests
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sluice.context import Context  # noqa: E402
from sluice.compressors.registry import compress  # noqa: E402
from sluice.estimator import estimate_tokens, savings_pct  # noqa: E402
from sluice.middleware import compress_messages  # noqa: E402


def c(text, cmd=None, source="shell"):
    ctx = Context.from_cmdline(cmd.split(), source=source) if cmd else Context(source=source)
    return compress(text, ctx)


class TestGit(unittest.TestCase):
    def test_push_success_collapses(self):
        out = c("To github.com:acme/shop.git\n   7f3..b2e  main -> main\n", "git push")[1]
        self.assertIn("ok push", out)
        self.assertIn("main -> main", out)

    def test_push_up_to_date(self):
        name, out = c("Everything up-to-date\n", "git push")
        self.assertEqual("ok: everything up-to-date", out)

    def test_push_error_keeps_all(self):
        txt = "error: failed to push some refs\nhint: updates were rejected\n"
        out = c(txt, "git push")[1]
        self.assertIn("failed to push", out)
        self.assertIn("rejected", out)

    def test_status_drops_hints(self):
        txt = 'Changes:\n  (use "git add <file>...")\n\tmodified: a.py\n'
        out = c(txt, "git status")[1]
        self.assertNotIn("(use ", out)
        self.assertIn("modified: a.py", out)


class TestTests(unittest.TestCase):
    def test_hides_passes_keeps_fail(self):
        txt = (
            "a::x PASSED\nb::y PASSED\nc::z FAILED\n"
            "========= 1 failed, 2 passed in 1.0s =========\n"
        )
        name, out = c(txt, "pytest")
        self.assertEqual(name, "tests")
        self.assertIn("FAILED", out)
        self.assertIn("1 failed, 2 passed", out)
        self.assertNotIn("x PASSED", out)


class TestGrep(unittest.TestCase):
    def test_groups_by_file(self):
        txt = "a.py:1:foo\na.py:9:foo\nb.py:3:foo\n"
        name, out = c(txt, "grep")
        self.assertEqual(name, "grep")
        self.assertIn("a.py: 2 ocorrencia", out)
        self.assertIn("b.py: 1 ocorrencia", out)


class TestJson(unittest.TestCase):
    def test_minify_is_lossless(self):
        obj = {"b": 1, "a": [1, 2, {"x": "y"}], "n": None}
        pretty = json.dumps(obj, indent=4)
        name, out = c(pretty, source="file")
        self.assertEqual(name, "json")
        self.assertNotIn("\n", out)
        self.assertEqual(json.loads(out), obj)


class TestLogs(unittest.TestCase):
    def test_hides_low_levels_when_errors_present(self):
        txt = "\n".join(
            ["2026 INFO boot"] * 3 + ["2026 DEBUG x"] * 3 + ["2026 ERROR boom"]
        )
        name, out = c(txt, source="file")
        self.assertEqual(name, "logs")
        self.assertIn("ERROR boom", out)
        self.assertNotIn("DEBUG x", out)


class TestGeneric(unittest.TestCase):
    def test_collapses_consecutive_duplicates(self):
        txt = "same\nsame\nsame\nother\n"
        name, out = c(txt, source="file")
        self.assertIn("(x3)", out)
        self.assertIn("other", out)


class TestEstimator(unittest.TestCase):
    def test_monotonic_and_savings(self):
        self.assertGreater(estimate_tokens("a" * 400), estimate_tokens("a" * 40))
        self.assertAlmostEqual(savings_pct(100, 25), 75.0)
        self.assertEqual(savings_pct(0, 0), 0.0)


class TestMiddleware(unittest.TestCase):
    def test_compresses_tool_result_only(self):
        big = "\n".join("src/x.py:%d:require_token(req)" % i for i in range(40))
        payload = {
            "model": "claude",
            "messages": [
                {"role": "user", "content": "por favor rode a busca"},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Bash",
                            "input": {"command": "grep -rn require_token src"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "t1",
                            "content": big,
                        }
                    ],
                },
            ],
        }
        saved = {}

        def _save(txt):
            saved["t"] = txt
            return "deadbeef"

        new, stats = compress_messages(payload, save_original=_save)
        # texto do usuario intacto
        self.assertEqual(new["messages"][0]["content"], "por favor rode a busca")
        # tool_result encolhido (ciente de comando: grep agrupa por arquivo)
        tr = new["messages"][2]["content"][0]["content"]
        self.assertIn("recall deadbeef", tr)
        self.assertIn("ocorrencia", tr)
        self.assertGreater(stats["saved_tokens_est"], 0)
        self.assertEqual(saved["t"], big)

    def test_dedup_entre_turnos(self):
        # mesma saida de grep aparece em dois turnos (arquivo "relido")
        big = "\n".join("src/x.py:%d:require_token(req)" % i for i in range(40))

        def tu(tid):
            return {"type": "tool_use", "id": tid, "name": "Bash",
                    "input": {"command": "grep -rn require_token src"}}

        def tr(tid):
            return {"type": "tool_result", "tool_use_id": tid, "content": big}

        payload = {
            "model": "claude",
            "messages": [
                {"role": "user", "content": "onde require_token aparece?"},
                {"role": "assistant", "content": [tu("a1")]},
                {"role": "user", "content": [tr("a1")]},
                {"role": "assistant", "content": [tu("a2")]},
                {"role": "user", "content": [tr("a2")]},
            ],
        }
        saved = []
        new, stats = compress_messages(
            payload, save_original=lambda t: (saved.append(t) or "h%d" % len(saved))
        )

        self.assertEqual(stats["tool_result_blocks"], 2)
        self.assertEqual(stats["dedup_blocks"], 1)

        first = new["messages"][2]["content"][0]["content"]   # copia antiga -> ponteiro
        last = new["messages"][4]["content"][0]["content"]    # copia recente -> comprimida
        self.assertIn("identica", first)
        self.assertNotIn("identica", last)
        self.assertNotIn("require_token(req)", first)   # conteudo bruto saiu da copia antiga
        self.assertIn("ocorrencia", last)               # a recente foi comprimida (grep)
        self.assertIn("recall", last)                   # e tem rodape de recuperacao


if __name__ == "__main__":
    unittest.main(verbosity=2)
