"""Teste de integracao do proxy (Fase 2) contra um upstream FALSO local.

Nao usa rede externa nem API key real. Verifica:
  * o corpo repassado ao provedor foi comprimido (tool_result bem menor);
  * headers sensiveis (x-api-key) sao repassados;
  * resposta em streaming (SSE) e transmitida intacta;
  * o original e recuperavel (store + endpoint /__sluice__/recall).

Rode com: python3 -m unittest discover -s tests
"""

import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sluice.proxy import build_server  # noqa: E402
from sluice.store import Store  # noqa: E402


def _extract_toolresult(payload) -> str:
    for msg in payload.get("messages", []):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                inner = block.get("content")
                if isinstance(inner, str):
                    return inner
                if isinstance(inner, list):
                    return "\n".join(
                        b.get("text", "")
                        for b in inner
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
    return ""


class _MockUpstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(n))
        tr = _extract_toolresult(payload)
        facts = {
            "saw_key": self.headers.get("x-api-key") is not None,
            "toolresult_chars": len(tr),
            "has_recall": "recall" in tr,
        }
        if payload.get("stream"):
            body = (
                "event: message_start\n"
                f"data: {json.dumps(facts)}\n\n"
                "event: message_stop\ndata: {}\n\n"
            ).encode("utf-8")
            ctype = "text/event-stream"
        else:
            body = json.dumps(facts).encode("utf-8")
            ctype = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        self.wfile.write(body)


class TestProxy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(path=os.path.join(self.tmp, "t.db"))

        self.up = ThreadingHTTPServer(("127.0.0.1", 0), _MockUpstream)
        up_port = self.up.server_address[1]
        threading.Thread(target=self.up.serve_forever, daemon=True).start()

        self.proxy = build_server(
            "127.0.0.1", 0, f"http://127.0.0.1:{up_port}", store=self.store
        )
        self.proxy_port = self.proxy.server_address[1]
        threading.Thread(target=self.proxy.serve_forever, daemon=True).start()

        self.big = "\n".join("src/x.py:%d:require_token(req)" % i for i in range(60))

    def tearDown(self):
        for srv in (self.proxy, self.up):
            srv.shutdown()
            srv.server_close()

    def _payload(self, stream):
        return {
            "model": "claude-x",
            "stream": stream,
            "messages": [
                {"role": "user", "content": "rode a busca"},
                {
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use", "id": "t1", "name": "Bash",
                        "input": {"command": "grep -rn require_token src"},
                    }],
                },
                {
                    "role": "user",
                    "content": [{
                        "type": "tool_result", "tool_use_id": "t1",
                        "content": self.big,
                    }],
                },
            ],
        }

    def _post(self, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.proxy_port}/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-api-key": "test-key-REDACTED",
                "anthropic-version": "2023-06-01",
            },
        )
        return urllib.request.urlopen(req, timeout=15)

    def test_nonstream_compresses_and_forwards(self):
        resp = self._post(self._payload(False))
        self.assertEqual(resp.status, 200)
        self.assertIn("X-Sluice-Saved-Pct-Est", resp.headers)
        facts = json.loads(resp.read())
        self.assertTrue(facts["saw_key"], "x-api-key deve ser repassado")
        self.assertTrue(facts["has_recall"], "footer de recall deve estar presente")
        self.assertLess(
            facts["toolresult_chars"], len(self.big) // 2,
            "o provedor deveria receber um tool_result bem menor",
        )

    def test_original_recuperavel(self):
        self._post(self._payload(False)).read()
        handle = hashlib.blake2b(
            self.big.encode("utf-8", "replace"), digest_size=6
        ).hexdigest()
        self.assertEqual(self.store.recall(handle), self.big)
        r = urllib.request.urlopen(
            f"http://127.0.0.1:{self.proxy_port}/__sluice__/recall/{handle}", timeout=15
        )
        self.assertEqual(r.read().decode("utf-8"), self.big)

    def test_stream_passthrough(self):
        resp = self._post(self._payload(True))
        self.assertEqual(resp.headers.get("Content-Type"), "text/event-stream")
        body = resp.read().decode("utf-8")
        self.assertIn("event: message_start", body)
        self.assertIn("message_stop", body)
        self.assertIn('"has_recall": true', body)

    def test_health_endpoint(self):
        r = urllib.request.urlopen(
            f"http://127.0.0.1:{self.proxy_port}/__sluice__/health", timeout=15
        )
        self.assertTrue(json.loads(r.read())["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
