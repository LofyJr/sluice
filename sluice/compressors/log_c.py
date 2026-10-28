"""Compressor de logs: colapsa repeticoes e esconde niveis baixos quando ha erros."""

import re
from collections import Counter

from ..context import Context
from .base import BaseCompressor

_LEVEL = re.compile(r"\b(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\b")
_LOW = {"TRACE", "DEBUG", "INFO"}
_HIGH = {"WARN", "WARNING", "ERROR", "FATAL", "CRITICAL"}


class LogCompressor(BaseCompressor):
    name = "logs"

    def matches(self, text: str, ctx: Context) -> bool:
        if ctx and ctx.argv0 in ("docker", "kubectl", "journalctl", "tail", "cat"):
            return True
        sample = "\n".join(text.splitlines()[:60])
        return len(_LEVEL.findall(sample)) >= 5

    def compress(self, text: str, ctx: Context) -> str:
        lines = text.splitlines()

        # colapsa linhas identicas consecutivas
        collapsed = []
        i, n = 0, len(lines)
        while i < n:
            j = i + 1
            while j < n and lines[j] == lines[i]:
                j += 1
            c = j - i
            collapsed.append(lines[i] + (f"  (x{c})" if c > 1 else ""))
            i = j

        levels = Counter(_LEVEL.findall(text))
        has_high = any(levels.get(l, 0) for l in _HIGH)
        if not has_high:
            return "\n".join(collapsed)

        out = []
        low = 0
        for ln in collapsed:
            m = _LEVEL.search(ln)
            lvl = m.group(1) if m else None
            if lvl in _LOW:
                low += 1
                continue
            out.append(ln)
        if low:
            out.insert(0, f"[{low} linha(s) INFO/DEBUG/TRACE ocultadas]")
        return "\n".join(out)
