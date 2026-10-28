"""Fase 2 — proxy local de requisicao (o sluice entre o cliente e o provedor).

Em cada requisicao para .../messages o proxy:
  1. le o corpo JSON (formato Anthropic Messages);
  2. comprime TODOS os blocos tool_result com compress_messages();
  3. salva cada original no store (recuperavel por handle);
  4. repassa a requisicao menor ao provedor e TRANSMITE a resposta de volta,
     inclusive streaming SSE, sem alterar.

Endpoints utilitarios (nao vao ao provedor):
  GET /__sluice__/health           -> status + upstream
  GET /__sluice__/stats            -> economia agregada estimada
  GET /__sluice__/recall/<handle>  -> original byte-a-byte

SEGURANCA (importante):
  * O proxy enxerga a sua API key e todo o conteudo dos prompts. Roda LOCAL.
  * Por padrao escuta em 127.0.0.1 (nao exposto na rede) e so repassa para o
    upstream configurado (default https://api.anthropic.com).
  * NUNCA loga o valor de x-api-key / authorization.
  * Expor em 0.0.0.0 publicaria um proxy que carrega a sua chave — nao faca isso
    sem necessidade e sem protecao de rede.
"""

import http.client
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .estimator import savings_pct
from .middleware import compress_messages

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}
DEFAULT_UPSTREAM = "https://api.anthropic.com"


def _connect(upstream: str, timeout: int = 600):
    u = urlparse(upstream)
    host = u.hostname
    port = u.port or (443 if u.scheme == "https" else 80)
    if u.scheme == "https":
        return http.client.HTTPSConnection(host, port, timeout=timeout)
    return http.client.HTTPConnection(host, port, timeout=timeout)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "sluice-proxy/0.1"

    def log_message(self, fmt, *args):
        if getattr(self.server, "verbose", False):
            sys.stderr.write("[sluice-proxy] " + (fmt % args) + "\n")

    # ---- GET: utilitarios do proxy -----------------------------------
    def do_GET(self):
        store = getattr(self.server, "store", None)
        if self.path.startswith("/__sluice__/recall/"):
            handle = self.path.rsplit("/", 1)[-1]
            content = store.recall(handle) if store else None
            if content is None:
                self._text(404, f"handle nao encontrado: {handle}")
            else:
                self._text(200, content)
            return
        if self.path == "/__sluice__/health":
            self._json(200, {"ok": True, "upstream": self.server.upstream})
            return
        if self.path == "/__sluice__/stats":
            if store:
                count, ot, ct, _ob, _cb = store.totals()
                self._json(200, {
                    "events": count,
                    "orig_tokens_est": ot,
                    "comp_tokens_est": ct,
                    "saved_pct_est": round(savings_pct(ot, ct), 1),
                })
            else:
                self._json(200, {"store": False})
            return
        self._text(404, "not found")

    # ---- POST: proxy das mensagens -----------------------------------
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""

        stats = None
        # compoe tanto /v1/messages quanto /v1/messages/count_tokens (mesmo shape)
        if ("messages" in self.path) and body:
            body, stats = self._maybe_compress(body)

        try:
            self._forward(body, stats)
        except Exception as exc:  # upstream fora do ar, timeout, etc.
            self._text(502, f"sluice-proxy: falha ao contatar upstream: {exc}")

    def _maybe_compress(self, body: bytes):
        try:
            payload = json.loads(body)
        except ValueError:
            return body, None
        if not isinstance(payload, dict) or "messages" not in payload:
            return body, None

        store = getattr(self.server, "store", None)
        save = store.save_original if store else None
        new_payload, stats = compress_messages(payload, save_original=save)
        new_body = json.dumps(new_payload, ensure_ascii=False).encode("utf-8")

        if store and stats["tool_result_blocks"]:
            store.log_event(
                source="proxy",
                command=str(payload.get("model") or ""),
                compressor="proxy",
                orig_tokens=stats["orig_tokens_est"],
                comp_tokens=stats["comp_tokens_est"],
                orig_bytes=len(body),
                comp_bytes=len(new_body),
                handle="",
            )
        if getattr(self.server, "verbose", False) and stats["tool_result_blocks"]:
            sys.stderr.write(
                f"[sluice-proxy] {stats['tool_result_blocks']} tool_result "
                f"({stats.get('dedup_blocks', 0)} dedup) "
                f"{stats['orig_tokens_est']}->{stats['comp_tokens_est']} tokens "
                f"(-{stats['saved_pct_est']}% est)\n"
            )
        return new_body, stats

    def _forward(self, body: bytes, stats):
        fwd = {}
        for k, v in self.headers.items():
            lk = k.lower()
            if lk in HOP_BY_HOP or lk in ("host", "content-length", "accept-encoding"):
                continue
            fwd[k] = v
        fwd["Content-Length"] = str(len(body))
        fwd["Accept-Encoding"] = "identity"

        conn = _connect(self.server.upstream)
        try:
            conn.request(self.command, self.path, body=body, headers=fwd)
            resp = conn.getresponse()

            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() in HOP_BY_HOP or k.lower() == "content-length":
                    continue
                self.send_header(k, v)
            if stats is not None:
                self.send_header("X-Sluice-Saved-Pct-Est", str(stats["saved_pct_est"]))
                self.send_header("X-Sluice-Blocks", str(stats["tool_result_blocks"]))
            self.send_header("Connection", "close")
            self.close_connection = True
            self.end_headers()

            # transmite a resposta conforme chega (funciona para SSE tambem)
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        finally:
            conn.close()

    # ---- helpers de resposta local -----------------------------------
    def _text(self, status: int, text: str):
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: int, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        self.wfile.write(data)


def build_server(host="127.0.0.1", port=8787, upstream=DEFAULT_UPSTREAM,
                 store=None, verbose=False) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.upstream = upstream.rstrip("/")
    httpd.store = store
    httpd.verbose = verbose
    return httpd


def run_proxy(host="127.0.0.1", port=8787, upstream=DEFAULT_UPSTREAM,
              store=None, verbose=False) -> int:
    httpd = build_server(host, port, upstream, store, verbose)
    sys.stderr.write(
        f"[sluice-proxy] escutando em http://{host}:{port}  ->  {httpd.upstream}\n"
        f"[sluice-proxy] aponte o cliente: export ANTHROPIC_BASE_URL=http://{host}:{port}\n"
        f"[sluice-proxy] ctrl-c para parar\n"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[sluice-proxy] encerrando\n")
    finally:
        httpd.server_close()
    return 0
