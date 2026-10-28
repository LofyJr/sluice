"""Estimativa de tokens.

IMPORTANTE: isto e uma ESTIMATIVA INFERIDA, nao a contagem oficial do provedor.
Serve para feedback rapido e para a razao de economia (orig vs comprimido), que e
estavel mesmo com um estimador aproximado. A porcentagem "de verdade" deve sempre
vir dos tokens de entrada reportados pelo provedor (ver PROPOSTA / sluice report).

O estimador combina duas aproximacoes classicas:
  * chars / 4            (bom para ingles e codigo);
  * soma de subpalavras  (palavras longas viram ~4 chars por token).
A media das duas reduz o vies de cada uma.
"""

import re

_WORD = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    subword = 0
    for piece in _WORD.findall(text):
        subword += max(1, (len(piece) + 3) // 4)
    char_based = len(text) / 4.0
    return int(round((subword + char_based) / 2.0))


def savings_pct(orig_tokens: int, comp_tokens: int) -> float:
    if orig_tokens <= 0:
        return 0.0
    return (1.0 - (comp_tokens / orig_tokens)) * 100.0
