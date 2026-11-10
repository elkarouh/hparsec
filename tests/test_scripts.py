"""Run the repository's self-testing scripts as one unittest suite.

Usage (from the repository root):
    python -m unittest discover tests
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
ZSH = ROOT / "tools" / "zsh_linter"


def _run(*args):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(SRC), env.get("PYTHONPATH", "")) if p
    )
    return subprocess.run(
        [sys.executable, "-B", *map(str, args)],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )


class ScriptTests(unittest.TestCase):
    def check(self, *args, expect=None):
        proc = _run(*args)
        output = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, output)
        if expect:
            self.assertIn(expect, output)

    def test_hparsec_selftest(self):
        self.check(SRC / "hparsec.py", expect="All tests passed.")

    def test_ady_tokenizer_selftest(self):
        self.check(SRC / "ady_tokenizer.py", expect="OK")

    def test_expression_parser(self):
        self.check(ROOT / "examples" / "expression_parser.py")

    def test_expression_parser_lr(self):
        self.check(ROOT / "examples" / "expression_parser_lr.py")

    def test_zsh_linter_cases(self):
        self.check(ZSH / "zsh_linter.py")

    def test_zsh_corpus(self):
        self.check(ZSH / "corpus_test.py", ZSH / "corpus", expect="(100%)")


if __name__ == "__main__":
    unittest.main()
