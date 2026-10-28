"""Compressor de JSON: minifica (remove apenas espacos em branco, sem perder dados)."""

import json

from ..context import Context
from .base import BaseCompressor


class JsonCompressor(BaseCompressor):
    name = "json"

    def matches(self, text: str, ctx: Context) -> bool:
        s = text.lstrip()
        if not s or s[0] not in "{[":
            return False
        try:
            json.loads(text)
            return True
        except (ValueError, RecursionError):
            return False

    def compress(self, text: str, ctx: Context) -> str:
        try:
            obj = json.loads(text)
        except (ValueError, RecursionError):
            return text
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
