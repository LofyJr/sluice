"""Contexto de uma compressao: de onde veio o texto e qual comando o gerou."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Context:
    """Metadados usados pelo registry para escolher o compressor certo.

    command    : linha de comando completa, ex. "git status".
    argv0      : programa, ex. "git".
    subcommand : primeiro token nao-flag depois do argv0, ex. "status".
    source     : "shell" | "file" | "stdin" | "payload".
    fmt        : dica explicita de formato ("json", "log", ...), opcional.
    """

    command: Optional[str] = None
    argv0: Optional[str] = None
    subcommand: Optional[str] = None
    source: str = "stdin"
    fmt: Optional[str] = None

    @classmethod
    def from_cmdline(cls, cmd_list, source: str = "shell") -> "Context":
        if not cmd_list:
            return cls(source=source)
        import os

        argv0 = os.path.basename(cmd_list[0])
        sub = None
        for tok in cmd_list[1:]:
            if not tok.startswith("-"):
                sub = tok
                break
        return cls(command=" ".join(cmd_list), argv0=argv0, subcommand=sub, source=source)
