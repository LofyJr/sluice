"""Armazenamento de recuperacao (thread-safe).

Toda compressao e LOSSY por design, mas o original e salvo ANTES de qualquer corte
e nunca e descartado automaticamente. Cada evento registra tokens/bytes antes e
depois, o compressor usado e o handle para recuperar o original byte-a-byte.

Backend: SQLite (stdlib). Caminho padrao: ./.sluice/sluice.db no diretorio atual,
sobreescrevivel por SLUICE_DB (arquivo) ou SLUICE_HOME (pasta).

O proxy (Fase 2) atende requisicoes em varias threads, entao a conexao e aberta
com check_same_thread=False e todo acesso ao banco e serializado por um Lock.
"""

import hashlib
import os
import sqlite3
import threading
import time
from typing import Optional


def _default_db() -> str:
    env = os.environ.get("SLUICE_DB")
    if env:
        return env
    home = os.environ.get("SLUICE_HOME") or os.path.join(os.getcwd(), ".sluice")
    return os.path.join(home, "sluice.db")


class Store:
    def __init__(self, path: Optional[str] = None):
        self.path = path or _default_db()
        parent = os.path.dirname(self.path) or "."
        os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self._init()

    def _init(self) -> None:
        with self._lock:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS blobs(
                    handle   TEXT PRIMARY KEY,
                    content  TEXT NOT NULL,
                    created  REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events(
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts          REAL NOT NULL,
                    source      TEXT,
                    command     TEXT,
                    compressor  TEXT,
                    orig_tokens INTEGER,
                    comp_tokens INTEGER,
                    orig_bytes  INTEGER,
                    comp_bytes  INTEGER,
                    handle      TEXT
                );
                """
            )
            self.db.commit()

    # ---- recuperacao -------------------------------------------------
    def save_original(self, content: str) -> str:
        """Guarda o original (idempotente por conteudo) e devolve o handle."""
        digest = hashlib.blake2b(content.encode("utf-8", "replace"), digest_size=6)
        handle = digest.hexdigest()
        with self._lock:
            self.db.execute(
                "INSERT OR IGNORE INTO blobs(handle, content, created) VALUES(?,?,?)",
                (handle, content, time.time()),
            )
            self.db.commit()
        return handle

    def recall(self, handle: str) -> Optional[str]:
        with self._lock:
            cur = self.db.execute(
                "SELECT content FROM blobs WHERE handle=?", (handle,)
            )
            row = cur.fetchone()
        return row[0] if row else None

    # ---- medicao -----------------------------------------------------
    def log_event(
        self,
        *,
        source: str,
        command: Optional[str],
        compressor: str,
        orig_tokens: int,
        comp_tokens: int,
        orig_bytes: int,
        comp_bytes: int,
        handle: str,
    ) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO events(ts,source,command,compressor,orig_tokens,"
                "comp_tokens,orig_bytes,comp_bytes,handle) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    time.time(),
                    source,
                    command,
                    compressor,
                    orig_tokens,
                    comp_tokens,
                    orig_bytes,
                    comp_bytes,
                    handle,
                ),
            )
            self.db.commit()

    def totals(self):
        with self._lock:
            cur = self.db.execute(
                "SELECT COUNT(*), COALESCE(SUM(orig_tokens),0), "
                "COALESCE(SUM(comp_tokens),0), COALESCE(SUM(orig_bytes),0), "
                "COALESCE(SUM(comp_bytes),0) FROM events"
            )
            return cur.fetchone()

    def by_group(self, column: str):
        # column e controlado internamente (compressor|command), nao vem do usuario.
        assert column in ("compressor", "command"), "coluna invalida"
        with self._lock:
            cur = self.db.execute(
                f"SELECT {column}, COUNT(*), COALESCE(SUM(orig_tokens),0), "
                f"COALESCE(SUM(comp_tokens),0) FROM events GROUP BY {column} "
                f"ORDER BY SUM(orig_tokens) DESC"
            )
            return cur.fetchall()
