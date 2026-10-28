"""Compressor ciente do git: status, push, log, diff."""

import re

from ..context import Context
from .base import HANDLE_TOKEN, BaseCompressor
from .generic import GenericCompressor


class GitCompressor(BaseCompressor):
    name = "git"

    def matches(self, text: str, ctx: Context) -> bool:
        return bool(ctx and ctx.argv0 == "git")

    def compress(self, text: str, ctx: Context) -> str:
        sub = (ctx.subcommand or "").lower()
        if sub == "status":
            return self._status(text)
        if sub == "push":
            return self._push(text)
        if sub == "log":
            return self._log(text)
        if sub in ("diff", "show"):
            return self._diff(text)
        return GenericCompressor().compress(text, ctx)

    def _status(self, text: str) -> str:
        keep = []
        for ln in text.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith("(use "):  # dicas do git, ruido puro para a IA
                continue
            keep.append(ln.rstrip())
        return "\n".join(keep) if keep else text

    def _push(self, text: str) -> str:
        lines = text.splitlines()
        if any("up-to-date" in l.lower() for l in lines):
            return "ok: everything up-to-date"
        if any(re.search(r"error|rejected|fatal|denied", l, re.I) for l in lines):
            return "\n".join(lines)  # em erro, mantem tudo
        refs = [l.strip() for l in lines if "->" in l]
        if refs:
            return "ok push:\n" + "\n".join(refs)
        return "\n".join(l for l in lines if l.strip())

    def _log(self, text: str) -> str:
        out = []
        sha = None
        subject = None
        for ln in text.splitlines():
            if ln.startswith("commit "):
                if sha:
                    out.append(f"{sha[:9]} {subject or ''}".rstrip())
                parts = ln.split()
                sha = parts[1] if len(parts) > 1 else ln[7:]
                subject = None
            elif ln.startswith(("Author:", "Date:", "Merge:")):
                continue
            elif subject is None and ln.strip():
                subject = ln.strip()
        if sha:
            out.append(f"{sha[:9]} {subject or ''}".rstrip())
        return "\n".join(out) if out else text

    def _diff(self, text: str) -> str:
        heads = (
            "diff --git",
            "index ",
            "--- ",
            "+++ ",
            "@@",
            "similarity",
            "rename ",
            "new file",
            "deleted file",
            "Binary files",
        )
        out = []
        added = removed = 0
        for ln in text.splitlines():
            if ln.startswith(heads):
                out.append(ln)
            elif ln.startswith("+"):
                added += 1
            elif ln.startswith("-"):
                removed += 1
        out.append(
            f"[diff resumido: +{added} / -{removed} linhas de conteudo "
            f"— original completo: sluice recall {HANDLE_TOKEN}]"
        )
        return "\n".join(out)
