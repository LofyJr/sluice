"""Contrato comum dos compressores."""

import abc

from ..context import Context

# Sentinela que os compressores inserem no lugar do handle de recuperacao.
# A CLI substitui por um handle real depois de salvar o original.
HANDLE_TOKEN = "\u27eaHANDLE\u27eb"


class BaseCompressor(abc.ABC):
    name = "base"

    @abc.abstractmethod
    def matches(self, text: str, ctx: Context) -> bool:
        """True se este compressor deve tratar este texto/contexto."""

    @abc.abstractmethod
    def compress(self, text: str, ctx: Context) -> str:
        """Devolve a versao reduzida. NUNCA deve lancar; em duvida, devolva o texto."""
