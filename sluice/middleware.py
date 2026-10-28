"""Camada de requisicao: o 'sluice' propriamente dito, entre seus prompts e a IA.

compress_messages() recebe um payload no formato Anthropic Messages e devolve uma
copia com o conteudo dos blocos tool_result comprimido. E essa funcao que um proxy
HTTP local (ou um middleware de SDK) chamaria em cada requisicao antes de repassar
para o provedor. Nao faz rede: e pura e testavel.

Modelo de dados esperado (subconjunto):
    {
      "model": "...",
      "messages": [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "...",
             "content": "<texto grande>"}  # ou lista de blocos {"type":"text","text":...}
        ]}
      ]
    }

Por que focar em tool_result: numa sessao de agente, a saida de ferramentas
(leitura de arquivo, shell, busca, MCP) costuma dominar os tokens de ENTRADA. E o
alvo de maior retorno. O texto do usuario e as instrucoes NAO sao tocados.
"""

import copy
from typing import Callable, Optional, Tuple

from .context import Context
from .compressors.registry import compress as _compress
from .estimator import estimate_tokens


def _collect_commands(messages) -> dict:
    """Mapeia tool_use_id -> comando, lendo os blocos tool_use (ex.: Bash do Claude Code).

    Permite que a saida de grep/git/pytest etc. receba compressao CIENTE DE COMANDO
    mesmo no nivel da requisicao, onde normalmente so havia o texto cru.
    """
    cmds = {}
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tid = block.get("id")
            inp = block.get("input")
            cmd = inp.get("command") if isinstance(inp, dict) else None
            if tid and isinstance(cmd, str) and cmd.strip():
                cmds[tid] = cmd
    return cmds


def _iter_tool_results(messages):
    """Gera (block, texto_original, setter) para cada tool_result, em ordem."""
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            inner = block.get("content")
            if isinstance(inner, str):
                text = inner

                def setter(v, b=block):
                    b["content"] = v
            elif isinstance(inner, list):
                texts = [
                    b.get("text", "")
                    for b in inner
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                if not texts:
                    continue
                text = "\n".join(texts)

                def setter(v, inner=inner):
                    done = False
                    for sub in inner:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            sub["text"] = v if not done else ""
                            done = True
            else:
                continue
            if not text.strip():
                continue
            yield block, text, setter


def compress_messages(
    payload: dict,
    *,
    save_original: Optional[Callable[[str], str]] = None,
    handle_note: bool = True,
    dedup: bool = True,
) -> Tuple[dict, dict]:
    """Comprime tool_result em um payload Messages.

    Duas otimizacoes compoem aqui:
      1) compressao ciente de formato/comando de cada tool_result;
      2) DE-DUPLICACAO ENTRE TURNOS: se a mesma saida aparece varias vezes no
         historico (arquivo relido, comando re-rodado), mantem so a ultima copia
         inteira e troca as anteriores por um ponteiro recuperavel. Em sessao
         longa isso corta muito, porque o historico e reenviado a cada turno.

    save_original: callback que persiste o original e devolve um handle.
    dedup: liga/desliga a de-duplicacao entre turnos (default: ligado).
    Retorna (novo_payload, stats).
    """
    new = copy.deepcopy(payload)
    cmds = _collect_commands(new.get("messages", []))

    collected = list(_iter_tool_results(new.get("messages", [])))

    # Indice da ULTIMA ocorrencia de cada texto identico (alvo da de-dup).
    last_index = {}
    if dedup:
        for i, (_b, text, _s) in enumerate(collected):
            last_index[text] = i

    orig_total = comp_total = 0
    blocks = dedup_blocks = 0

    for i, (block, text, setter) in enumerate(collected):
        ot = estimate_tokens(text)

        # Duplicata entre turnos: nao e a ultima copia -> vira ponteiro recuperavel.
        if dedup and last_index.get(text) != i:
            ref = "um passo posterior deste chat"
            if save_original is not None:
                ref = f"recall {save_original(text)}"
            out = f"[sluice: saida identica a de {ref} — omitida para economizar]"
            ct = estimate_tokens(out)
            setter(out)
            orig_total += ot
            comp_total += ct
            blocks += 1
            dedup_blocks += 1
            continue

        # Caso normal: compressao ciente de comando/formato.
        cmd = cmds.get(block.get("tool_use_id"))
        ctx = (
            Context.from_cmdline(cmd.split(), source="tool_result")
            if cmd
            else Context(source="tool_result")
        )
        name, out = _compress(text, ctx)
        ct = estimate_tokens(out)
        if save_original is not None and out != text:
            handle = save_original(text)
            if handle_note:
                out = f"{out}\n[sluice {name}: original completo via recall {handle}]"
                ct = estimate_tokens(out)
        setter(out)
        orig_total += ot
        comp_total += ct
        blocks += 1

    saved_pct = (1.0 - comp_total / orig_total) * 100.0 if orig_total else 0.0
    stats = {
        "tool_result_blocks": blocks,
        "dedup_blocks": dedup_blocks,
        "orig_tokens_est": orig_total,
        "comp_tokens_est": comp_total,
        "saved_tokens_est": orig_total - comp_total,
        "saved_pct_est": round(saved_pct, 1),
    }
    return new, stats
