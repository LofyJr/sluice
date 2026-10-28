"""Compressor de builds/instaladores: guarda erros e avisos, colapsa progresso."""

import re

from ..context import Context
from .base import BaseCompressor

_KEEP = re.compile(
    r"(error|warning|failed|panic|cannot|undefined|exception|deprecat)", re.I
)
_PROGRESS = re.compile(
    r"^\s*(Compiling|Compiled|Downloading|Downloaded|Fetching|Fetched|Installing|"
    r"Installed|added|removed|changed|Building|Resolving|Resolved|Updating|"
    r"Preparing|Unpacking|Extracting|npm warn deprecated\b)",
    re.I,
)


class BuildCompressor(BaseCompressor):
    name = "build"

    def matches(self, text: str, ctx: Context) -> bool:
        if not ctx or not ctx.argv0:
            return False
        if ctx.argv0 in (
            "cargo", "make", "gcc", "g++", "clang", "tsc",
            "webpack", "vite", "rollup", "esbuild", "gradle", "mvn",
        ):
            return True
        if ctx.argv0 in ("npm", "pnpm", "yarn") and ctx.subcommand in (
            "run", "build", "ci", "install", "i", "add",
        ):
            return True
        return False

    def compress(self, text: str, ctx: Context) -> str:
        kept = []
        progress = 0
        for ln in text.splitlines():
            if _KEEP.search(ln):
                kept.append(ln.rstrip())
                continue
            if _PROGRESS.search(ln):
                progress += 1
                continue
            if not ln.strip():
                continue
            kept.append(ln.rstrip())

        # colapsa duplicatas consecutivas que sobraram
        dedup = []
        for ln in kept:
            if dedup and dedup[-1] == ln:
                continue
            dedup.append(ln)

        if progress:
            dedup.insert(0, f"[{progress} linha(s) de progresso de build ocultadas]")
        return "\n".join(dedup) if dedup else text
