"""Compressor de test runners: mostra falhas, colapsa os testes que passaram."""

import re

from ..context import Context
from .base import BaseCompressor

_FAIL = re.compile(r"(FAIL|FAILED|ERROR|✕|×|AssertionError|Traceback|Error:)")
_PASS = re.compile(r"(\bPASS(ED)?\b|^\s*ok\b|✓|·|PASSED)")
_SUMMARY_LINE = re.compile(r"(passed|failed|error|skipped|broken)", re.I)


class TestCompressor(BaseCompressor):
    name = "tests"

    def matches(self, text: str, ctx: Context) -> bool:
        if not ctx or not ctx.argv0:
            return False
        if ctx.argv0 in ("pytest", "py.test", "jest", "vitest", "mocha", "ava"):
            return True
        if ctx.argv0 == "go" and ctx.subcommand == "test":
            return True
        if ctx.argv0 in ("npm", "pnpm", "yarn") and ctx.subcommand == "test":
            return True
        return False

    def compress(self, text: str, ctx: Context) -> str:
        kept = []
        passes = 0
        in_fail = False
        for ln in text.splitlines():
            stripped = ln.strip()
            # linha de resumo final (ex.: "=== 2 failed, 118 passed in 3.1s ===")
            if _SUMMARY_LINE.search(ln) and re.search(r"\d", ln) and (
                "passed" in ln.lower() or "failed" in ln.lower()
            ):
                kept.append(ln.rstrip())
                in_fail = False
                continue
            if _FAIL.search(ln):
                kept.append(ln.rstrip())
                in_fail = True
                continue
            if _PASS.search(ln) and not _FAIL.search(ln):
                passes += 1
                in_fail = False
                continue
            if in_fail and stripped:
                kept.append(ln.rstrip())
                continue
        header = [f"[{passes} teste(s) que passaram foram ocultados]"] if passes else []
        body = header + kept
        return "\n".join(body) if body else text
