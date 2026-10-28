"""Compressor generico: o piso seguro para qualquer texto.

- normaliza quebras de linha e espacos a direita;
- colapsa linhas identicas consecutivas em "linha  (xN)";
- reduz sequencias de linhas em branco;
- trunca o meio de saidas muito longas, mantendo cabeca e cauda.
"""

import re

from ..context import Context
from .base import HANDLE_TOKEN, BaseCompressor

_BLANK_RUN = re.compile(r"\n[ \t]*\n[ \t]*\n+")


class GenericCompressor(BaseCompressor):
    name = "generic"

    def __init__(self, max_lines: int = 400, head: int = 60, tail: int = 40):
        self.max_lines = max_lines
        self.head = head
        self.tail = tail

    def matches(self, text: str, ctx: Context) -> bool:
        return True

    def compress(self, text: str, ctx: Context) -> str:
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        lines = [ln.rstrip() for ln in lines]

        out = []
        i, n = 0, len(lines)
        while i < n:
            j = i + 1
            while j < n and lines[j] == lines[i]:
                j += 1
            count = j - i
            if count > 1 and lines[i].strip():
                out.append(f"{lines[i]}  (x{count})")
            else:
                out.append(lines[i])
            i = j

        text2 = _BLANK_RUN.sub("\n\n", "\n".join(out))

        res = text2.split("\n")
        if len(res) > self.max_lines:
            elided = len(res) - self.head - self.tail
            marker = (
                f"[... {elided} linhas omitidas "
                f"— original: sluice recall {HANDLE_TOKEN} ...]"
            )
            res = res[: self.head] + [marker] + res[-self.tail :]
            text2 = "\n".join(res)
        return text2
