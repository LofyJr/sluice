# Sluice

**A token-saving proxy that sits between your prompts and the AI.** It lets the
signal through, holds back the noise, and keeps every original behind the gate —
byte-exact recoverable.

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![deps](https://img.shields.io/badge/dependencies-none-brightgreen)](#requirements)
[![license](https://img.shields.io/badge/license-MIT-lightgrey)](#license)

**Languages:** English (below) · [Português](#português)

> Not affiliated with Anthropic. "Claude" and "Claude Code" are trademarks of their
> respective owners. Sluice is an independent, local tool.

---

## What it is

Agentic coding sessions burn most of their **input** tokens on tool output
(file reads, shell results, search, logs, MCP responses) — and that history is
re-sent to the model on every turn. Sluice shrinks that waste without losing
information:

- **Format/command-aware compression** of tool output (git, test runners, builds,
  grep, file listings, logs, JSON) — the signal stays, the noise goes.
- **Cross-turn de-duplication:** when the same output repeats in the history
  (a re-read file, a re-run command), older copies collapse to a recoverable
  pointer and only the most recent full copy survives.
- **Byte-exact recovery:** every original is stored first and fetched back with a
  handle, so compression is never destructive.

```
WITHOUT Sluice:
   Claude Code  ───────────────────────────►  Anthropic API

WITH Sluice:
   Claude Code ──►  Sluice (local, 127.0.0.1)  ──►  Anthropic API
                    compress + de-dup, originals kept
```

## Results

In a self-contained A/B benchmark (`tools/ab_validate.py`) on identical payloads:

| Scenario | Input tokens | Saved |
|---|---|---|
| Single agent turn (compression only) | 1934 → 933 | **~52%** |
| Multi-turn session (compression + cross-turn de-dup) | 2339 → 557 | **~76%** |

These are **internal estimates** for feedback. The official figure should come
from the provider-reported input tokens for the same, successfully completed task.

## Requirements

- Python 3.9+ (tested on 3.14). **No external dependencies.**
- [Claude Code](https://www.anthropic.com/) installed — only for the proxy use.

## Quick start (CLI)

```bash
# run a command and return its compressed output (original is stored)
./bin/sluice shrink -- git status
./bin/sluice shrink -- pytest -q

# compress a file or stdin
./bin/sluice compress path/to/file.log
cat build.log | ./bin/sluice compress - --cmd "cargo build"

# fetch the original back, byte-for-byte
./bin/sluice recall <handle>

# aggregate savings report (internal estimate)
./bin/sluice report

# benchmark on the bundled examples
./bin/sluice demo
```

Compressed output goes to **stdout**; the savings footer and recovery `handle`
go to **stderr**, so pipes stay clean.

## Use it with Claude Code

The multi-turn saving (compression + cross-turn de-dup) is **automatic** — there
is nothing to switch on. You only need Claude Code to talk to Sluice.

**One command** (run from the project folder, in a terminal):

```bash
./bin/sluice-claude
```

It (1) starts the proxy if it isn't running, (2) points Claude Code at it, and
(3) opens Claude Code already wired up. Use the chat normally.

**Verify it's saving** — after a few tool-using prompts, in another terminal:

```bash
curl -s http://127.0.0.1:8799/__sluice__/stats
```

Non-zero numbers (e.g. `"saved_pct_est": 61.0`) mean it's working. All zeros means
Claude Code isn't routing through Sluice (see the subscription note).

**Stop** it anytime:

```bash
pkill -f "sluice proxy"
```

> **Subscription note.** With an **API key**, this works cleanly and cuts billed
> tokens. With a **Pro/Max subscription (OAuth login)**, some Claude Code versions
> ignore `ANTHROPIC_BASE_URL` (the stats stay zero), and routing subscription
> traffic through a proxy may be flagged by the provider. The `stats` check above
> tells you immediately whether requests are passing through.

### Proxy, manually (two terminals)

```bash
# terminal 1 — start the proxy (default upstream: https://api.anthropic.com)
./bin/sluice proxy --port 8799

# terminal 2 — point your Anthropic client at it, then launch it
export ANTHROPIC_BASE_URL=http://127.0.0.1:8799
# your ANTHROPIC_API_KEY stays in the client and is only forwarded
```

Proxy-only endpoints (they never reach the provider):

| Endpoint | Purpose |
|---|---|
| `GET /__sluice__/health` | status + upstream |
| `GET /__sluice__/stats` | aggregated savings (estimate) |
| `GET /__sluice__/recall/<handle>` | original, byte-for-byte |

Each proxied response carries `X-Sluice-Saved-Pct-Est` and `X-Sluice-Blocks`.

## Architecture

| Layer | File | Role |
|---|---|---|
| Shell-shrink (command-aware) | `sluice/compressors/*` + `sluice shrink` | trim git, test, build, grep, ls, logs, json |
| Request middleware | `sluice/middleware.py` | `compress_messages()` + cross-turn de-dup |
| Local proxy | `sluice/proxy.py` + `sluice proxy` | sits between client and provider; SSE streaming |
| Recovery store | `sluice/store.py` | always keeps the original; `recall <handle>` (thread-safe) |
| Measurement | `sluice/store.py` + `sluice report` | savings per compressor/command |

## Configuration

- `SLUICE_DB` — SQLite store path (default `./.sluice/sluice.db`).
- `SLUICE_HOME` — base folder for the store (alternative to `SLUICE_DB`).
- `SLUICE_PORT` — proxy port used by `sluice-claude` (default `8799`).
- `SLUICE_UPSTREAM` — upstream base URL (default `https://api.anthropic.com`).

## Security

The proxy sees your API key and all prompt content. It runs **locally**, binds to
`127.0.0.1` by default, forwards only to the configured upstream, and **never logs
the key value**. Do not bind it to `0.0.0.0` without network protection. The
recovery store (`.sluice/`) may hold original tool output and is git-ignored —
never commit it.

## Testing

```bash
python3 -m unittest discover -s tests
python3 tools/ab_validate.py     # A/B: same payload, with vs without the tunnel
```

## License

Released under the [MIT License](LICENSE).

---

# Português

**Um proxy que economiza tokens, entre os seus prompts e a IA.** Ele deixa o sinal
passar, segura o ruído e guarda todo original atrás da comporta — recuperável byte
a byte.

**Idiomas:** [English](#sluice) · Português (abaixo)

> Sem afiliação com a Anthropic. "Claude" e "Claude Code" são marcas de seus
> respectivos donos. O Sluice é uma ferramenta local e independente.

## O que é

Sessões de agente gastam a maior parte dos tokens de **entrada** com saída de
ferramenta (leitura de arquivo, shell, busca, logs, respostas de MCP) — e esse
histórico é reenviado à IA a cada turno. O Sluice corta esse desperdício sem
perder informação:

- **Compressão ciente de formato/comando** da saída (git, test runners, builds,
  grep, listagens, logs, JSON) — fica o sinal, sai o ruído.
- **De-duplicação entre turnos:** quando a mesma saída se repete no histórico
  (arquivo relido, comando re-rodado), as cópias antigas viram um ponteiro
  recuperável e só a mais recente fica inteira.
- **Recuperação byte a byte:** todo original é guardado antes de encolher e volta
  por um `handle`, então a compressão nunca é destrutiva.

```
SEM o Sluice:
   Claude Code  ───────────────────────────►  API da Anthropic

COM o Sluice:
   Claude Code ──►  Sluice (local, 127.0.0.1)  ──►  API da Anthropic
                    comprime + de-dup, guarda os originais
```

## Resultados

Em um benchmark A/B fechado (`tools/ab_validate.py`), com payloads idênticos:

| Cenário | Tokens de entrada | Economia |
|---|---|---|
| Turno único (só compressão) | 1934 → 933 | **~52%** |
| Sessão multi-turno (compressão + de-dup entre turnos) | 2339 → 557 | **~76%** |

São **estimativas internas**, para feedback. O número oficial deve vir dos tokens
de entrada reportados pelo provedor, para a mesma tarefa concluída com sucesso.

## Requisitos

- Python 3.9+ (testado em 3.14). **Sem dependências externas.**
- [Claude Code](https://www.anthropic.com/) instalado — só para o uso com proxy.

## Início rápido (CLI)

```bash
# roda um comando e devolve a saída comprimida (original fica salvo)
./bin/sluice shrink -- git status
./bin/sluice shrink -- pytest -q

# comprime um arquivo ou stdin
./bin/sluice compress caminho/arquivo.log
cat build.log | ./bin/sluice compress - --cmd "cargo build"

# recupera o original byte a byte
./bin/sluice recall <handle>

# relatório de economia agregada (estimativa interna)
./bin/sluice report

# benchmark nos exemplos embutidos
./bin/sluice demo
```

A saída comprimida vai para o **stdout**; o rodapé com a economia e o `handle` de
recuperação vão para o **stderr** (não poluem pipes).

## Usar com o Claude Code

A economia multi-turno (compressão + de-dup entre turnos) é **automática** — não
há nada para ligar. Basta o Claude Code falar com o Sluice.

**Um comando só** (rode dentro da pasta do projeto, no Terminal):

```bash
./bin/sluice-claude
```

Ele (1) sobe o proxy se não estiver no ar, (2) aponta o Claude Code para ele e
(3) abre o Claude Code já conectado. Use o chat normalmente.

**Conferir que está economizando** — após alguns prompts que mexam em
arquivos/comandos, em outro Terminal:

```bash
curl -s http://127.0.0.1:8799/__sluice__/stats
```

Números maiores que zero (ex.: `"saved_pct_est": 61.0`) = funcionando. Tudo zero =
o Claude Code não está passando pelo Sluice (ver nota de assinatura).

**Desligar** quando quiser:

```bash
pkill -f "sluice proxy"
```

> **Nota de assinatura.** Com **API key**, funciona limpo e corta tokens cobrados.
> Com **assinatura Pro/Max (login OAuth)**, algumas versões do Claude Code ignoram
> o `ANTHROPIC_BASE_URL` (o stats fica zerado), e rotear tráfego de assinatura por
> um proxy pode ser sinalizado pelo provedor. O teste do `stats` acima diz na hora
> se as requisições estão passando.

### Proxy, manual (dois terminais)

```bash
# terminal 1 — sobe o proxy (upstream padrão: https://api.anthropic.com)
./bin/sluice proxy --port 8799

# terminal 2 — aponte seu cliente Anthropic para ele e abra
export ANTHROPIC_BASE_URL=http://127.0.0.1:8799
# sua ANTHROPIC_API_KEY continua no cliente e é apenas repassada
```

Endpoints só do proxy (não vão ao provedor):

| Endpoint | Para quê |
|---|---|
| `GET /__sluice__/health` | status + upstream |
| `GET /__sluice__/stats` | economia agregada (estimativa) |
| `GET /__sluice__/recall/<handle>` | original, byte a byte |

Cada resposta proxyada leva `X-Sluice-Saved-Pct-Est` e `X-Sluice-Blocks`.

## Arquitetura

| Camada | Arquivo | Papel |
|---|---|---|
| Shell-shrink (ciente de comando) | `sluice/compressors/*` + `sluice shrink` | corta git, test, build, grep, ls, logs, json |
| Middleware de requisição | `sluice/middleware.py` | `compress_messages()` + de-dup entre turnos |
| Proxy local | `sluice/proxy.py` + `sluice proxy` | entre cliente e provedor; streaming SSE |
| Store de recuperação | `sluice/store.py` | guarda sempre o original; `recall <handle>` (thread-safe) |
| Medição | `sluice/store.py` + `sluice report` | economia por compressor/comando |

## Configuração

- `SLUICE_DB` — caminho do SQLite do store (padrão `./.sluice/sluice.db`).
- `SLUICE_HOME` — pasta base do store (alternativa a `SLUICE_DB`).
- `SLUICE_PORT` — porta do proxy usada pelo `sluice-claude` (padrão `8799`).
- `SLUICE_UPSTREAM` — URL base do upstream (padrão `https://api.anthropic.com`).

## Segurança

O proxy enxerga a sua API key e todo o conteúdo dos prompts. Ele roda **local**,
escuta em `127.0.0.1` por padrão, só repassa para o upstream configurado e **nunca
loga o valor da chave**. Não exponha em `0.0.0.0` sem proteção de rede. O store de
recuperação (`.sluice/`) pode conter saída original de ferramentas e está no
`.gitignore` — nunca faça commit dele.

## Testes

```bash
python3 -m unittest discover -s tests
python3 tools/ab_validate.py     # A/B: mesmo payload, com e sem o túnel
```

## Licença

Distribuído sob a [Licença MIT](LICENSE).
