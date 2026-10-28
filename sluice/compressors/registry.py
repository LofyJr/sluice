"""Escolha do compressor e aplicacao com rede de seguranca.

Ordem: cientes-de-comando primeiro, depois cientes-de-conteudo, por fim o generico.
Apos um compressor especializado, se a saida ainda estiver muito grande, aplica o
truncamento do generico como rede de seguranca.
"""

from ..context import Context
from .build_c import BuildCompressor
from .filelist_c import FileListCompressor
from .generic import GenericCompressor
from .git_c import GitCompressor
from .grep_c import GrepCompressor
from .json_c import JsonCompressor
from .log_c import LogCompressor
from .tests_c import TestCompressor

_PIPELINE = [
    GitCompressor(),
    TestCompressor(),
    BuildCompressor(),
    GrepCompressor(),
    FileListCompressor(),
    JsonCompressor(),
    LogCompressor(),
]
_GENERIC = GenericCompressor()


def choose(text: str, ctx: Context):
    for comp in _PIPELINE:
        try:
            if comp.matches(text, ctx):
                return comp
        except Exception:
            continue
    return _GENERIC


def compress(text: str, ctx: Context):
    """Devolve (nome_do_compressor, texto_comprimido)."""
    if not text:
        return "noop", text
    comp = choose(text, ctx)
    try:
        out = comp.compress(text, ctx)
    except Exception:
        # qualquer falha de compressor nunca pode quebrar o fluxo
        return "noop", text
    name = comp.name
    # rede de seguranca: trunca se ainda estiver enorme
    if comp is not _GENERIC and out.count("\n") > _GENERIC.max_lines:
        out = _GENERIC.compress(out, ctx)
    return name, out
