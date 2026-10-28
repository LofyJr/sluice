"""Validacao A/B: o MESMO prompt consome menos passando pelo sluice?

Nao da para dirigir a UI do Kiro nem rotear a inferencia do proprio Kiro pelo
sluice. Entao este harness faz o equivalente fiel ao pedido ("duas guias, mesmo
prompt, com e sem o sluice"): monta UM turno de agente realista (pergunta do
usuario + tool_use + tool_result grandes) e mede os TOKENS DE ENTRADA que chegam
ao provedor nas duas rotas:

  A) SEM SLUICE  : payload vai direto ao upstream.
  B) PELO SLUICE : payload passa pelo proxy (que comprime tool_result) e so entao
                  chega ao upstream.

O upstream aqui e um mock local que conta os tokens de entrada do payload
recebido (mesmo metodo nas duas rotas -> a diferenca e real). Se um dia houver
ANTHROPIC_API_KEY, basta trocar o upstream por https://api.anthropic.com e usar
/v1/messages/count_tokens, que o numero passa a ser o oficial do provedor.

Uso: python3 tools/ab_validate.py
"""

import json
import os
import sys
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from sluice.estimator import estimate_tokens, savings_pct  # noqa: E402
from sluice.proxy import build_server  # noqa: E402
from sluice.store import Store  # noqa: E402


def count_input_tokens(payload: dict) -> int:
    """Conta tokens de entrada do payload (mesma forma que o provedor veria)."""
    total = 0
    for msg in payload.get("messages", []):
        content = msg.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                t = b.get("type")
                if t == "text":
                    total += estimate_tokens(b.get("text", ""))
                elif t == "tool_use":
                    total += estimate_tokens(json.dumps(b.get("input", {})))
                elif t == "tool_result":
                    inner = b.get("content")
                    if isinstance(inner, str):
                        total += estimate_tokens(inner)
                    elif isinstance(inner, list):
                        for sub in inner:
                            if isinstance(sub, dict) and sub.get("type") == "text":
                                total += estimate_tokens(sub.get("text", ""))
    return total


class _CountingUpstream(BaseHTTPRequestHandler):
    """Mock do provedor: responde como /v1/messages/count_tokens."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(n) or b"{}")
        body = json.dumps({"input_tokens": count_input_tokens(payload)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        self.wfile.write(body)


def _post(url: str, payload: dict):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": "dummy-local",
            "anthropic-version": "2023-06-01",
        },
    )
    resp = urllib.request.urlopen(req, timeout=20)
    return resp, json.loads(resp.read())


def _load(name: str) -> str:
    with open(os.path.join(_REPO, "examples", name), encoding="utf-8") as f:
        return f.read()


def build_payload() -> dict:
    """UM turno de agente realista, igual nos dois lados do teste."""
    return {
        "model": "claude-opus-4.8",
        "max_tokens": 1024,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Investiga por que o checkout falha: mostra onde require_token "
                    "e usado, roda os testes e olha o log do servidor."
                ),
            },
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Vou buscar o uso, rodar os testes e ver o log."},
                    {"type": "tool_use", "id": "u1", "name": "Bash",
                     "input": {"command": "grep -rn require_token src tests docs"}},
                    {"type": "tool_use", "id": "u2", "name": "Bash",
                     "input": {"command": "pytest -q"}},
                    {"type": "tool_use", "id": "u3", "name": "Bash",
                     "input": {"command": "cat logs/server.log"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "u1", "content": _load("grep.txt")},
                    {"type": "tool_result", "tool_use_id": "u2", "content": _load("pytest.txt")},
                    {"type": "tool_result", "tool_use_id": "u3", "content": _load("server.log")},
                ],
            },
        ],
    }


def build_payload_multiturn() -> dict:
    """Sessao com varios passos: o agente RELE o mesmo log 3x e repete um grep 2x.
    E o caso em que a de-duplicacao entre turnos brilha (historico reenviado)."""
    log = _load("server.log")
    grep = _load("grep.txt")

    def tu(tid, cmd):
        return {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}

    def tr(tid, content):
        return {"type": "tool_result", "tool_use_id": tid, "content": content}

    msgs = [{"role": "user", "content": "Debugue o servidor passo a passo."}]
    for k in range(3):
        msgs.append({"role": "assistant", "content": [tu(f"l{k}", "cat logs/server.log")]})
        msgs.append({"role": "user", "content": [tr(f"l{k}", log)]})
    for k in range(2):
        msgs.append({"role": "assistant", "content": [tu(f"g{k}", "grep -rn require_token src")]})
        msgs.append({"role": "user", "content": [tr(f"g{k}", grep)]})
    return {"model": "claude-opus-4.8", "max_tokens": 1024, "messages": msgs}


def run_ab(label: str, payload: dict, up_port: int, px_port: int):
    _, a = _post(f"http://127.0.0.1:{up_port}/v1/messages/count_tokens", payload)
    resp_b, b = _post(f"http://127.0.0.1:{px_port}/v1/messages/count_tokens", payload)
    in_a, in_b = a["input_tokens"], b["input_tokens"]
    print(label)
    print(f"   SEM SLUICE  (direto) : input_tokens = {in_a}")
    print(f"   PELO SLUICE (proxy)  : input_tokens = {in_b}")
    print(f"   -> economia: -{savings_pct(in_a, in_b):.0f}%  ({in_a - in_b} tokens a menos)")
    print()
    return in_a, in_b


def main() -> int:
    tmp = tempfile.mkdtemp()
    store = Store(path=os.path.join(tmp, "ab.db"))

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _CountingUpstream)
    up_port = upstream.server_address[1]
    threading.Thread(target=upstream.serve_forever, daemon=True).start()

    proxy = build_server("127.0.0.1", 0, f"http://127.0.0.1:{up_port}", store=store)
    px_port = proxy.server_address[1]
    threading.Thread(target=proxy.serve_forever, daemon=True).start()

    line = "=" * 64
    try:
        print(line)
        print("VALIDACAO A/B — mesmo prompt, com e sem o sluice")
        print(line)
        a1, b1 = run_ab(
            "CENARIO 1 — turno unico (so compressao de saida):",
            build_payload(), up_port, px_port,
        )
        a2, b2 = run_ab(
            "CENARIO 2 — sessao multi-turno (compressao + de-dup entre turnos):",
            build_payload_multiturn(), up_port, px_port,
        )
        print(line)
        if not (b1 < a1 and b2 < a2):
            print("FALHA: o sluice nao reduziu o consumo em algum cenario.")
            return 1
        print("OK: o mesmo prompt consome menos passando pelo sluice.")
        print("    A de-dup multi-turno corta ainda mais quando o historico se repete.")
        print("    (nada foi perdido: cada original tem handle para 'sluice recall')")
        return 0
    finally:
        proxy.shutdown(); proxy.server_close()
        upstream.shutdown(); upstream.server_close()


if __name__ == "__main__":
    sys.exit(main())
