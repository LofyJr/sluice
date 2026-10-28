"""Compressor de listagens (ls/tree/find/fd): corta listas longas."""

from ..context import Context
from .base import HANDLE_TOKEN, BaseCompressor

_HEAD = 40


class FileListCompressor(BaseCompressor):
    name = "filelist"

    def matches(self, text: str, ctx: Context) -> bool:
        return bool(ctx and ctx.argv0 in ("ls", "tree", "find", "fd"))

    def compress(self, text: str, ctx: Context) -> str:
        lines = [l for l in text.splitlines() if l.strip()]
        n = len(lines)
        if n <= _HEAD:
            return "\n".join(lines)
        shown = lines[:_HEAD]
        shown.append(
            f"(+{n - _HEAD} entradas a mais — total {n}; "
            f"original: sluice recall {HANDLE_TOKEN})"
        )
        return "\n".join(shown)
