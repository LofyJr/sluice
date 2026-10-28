"""Compressor de busca (grep/rg/ag): agrupa ocorrencias por arquivo."""

import re

from ..context import Context
from .base import BaseCompressor

_SAMPLE_PER_FILE = 2


class GrepCompressor(BaseCompressor):
    name = "grep"

    def matches(self, text: str, ctx: Context) -> bool:
        return bool(ctx and ctx.argv0 in ("grep", "rg", "ag", "ack"))

    def compress(self, text: str, ctx: Context) -> str:
        by_file = {}
        order = []
        for ln in text.splitlines():
            if not ln.strip():
                continue
            m = re.match(r"([^:]+):", ln)
            key = m.group(1) if m else "(sem arquivo)"
            if key not in by_file:
                by_file[key] = []
                order.append(key)
            by_file[key].append(ln)

        if not order:
            return text

        out = []
        for key in order:
            matches = by_file[key]
            out.append(f"{key}: {len(matches)} ocorrencia(s)")
            for sample in matches[:_SAMPLE_PER_FILE]:
                out.append("  " + sample)
            if len(matches) > _SAMPLE_PER_FILE:
                out.append(f"  (+{len(matches) - _SAMPLE_PER_FILE} mais)")
        return "\n".join(out)
