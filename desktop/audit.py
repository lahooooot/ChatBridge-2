"""Concurrent SQLite audit trail for real tool outcomes."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

MAX_AUDIT_PAYLOAD = 2 * 1024 * 1024


def _serialize(value):
    text = json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)
    if len(text.encode("utf-8")) > MAX_AUDIT_PAYLOAD:
        return json.dumps({"truncated": True, "preview": text[:16000]}, ensure_ascii=False)
    return text


class AuditLog:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA busy_timeout=30000")
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
            self._connection.execute("""CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                tool TEXT NOT NULL,
                args TEXT NOT NULL,
                ok INTEGER NOT NULL,
                result TEXT,
                error TEXT
            )""")
            self._connection.commit()

    def record(self, tool, args, ok, result=None, error=None):
        if not isinstance(tool, str) or not tool or len(tool) > 128:
            raise ValueError("Audit tool name must be a nonempty string of at most 128 characters")
        if not isinstance(ok, bool):
            raise ValueError("Audit ok must be a boolean")
        values = (datetime.now(timezone.utc).isoformat(), tool, _serialize(args), int(ok),
                  _serialize(result) if result is not None else None,
                  str(error)[:16000] if error is not None else None)
        with self._lock, self._connection:
            cursor = self._connection.execute("INSERT INTO audit(timestamp,tool,args,ok,result,error) VALUES (?,?,?,?,?,?)", values)
            return cursor.lastrowid

    def recent(self, limit=100) -> list:
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("Audit limit must be between 1 and 10000")
        with self._lock:
            rows = self._connection.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": row["id"], "timestamp": row["timestamp"], "tool": row["tool"],
                 "args": json.loads(row["args"]), "ok": bool(row["ok"]),
                 "result": json.loads(row["result"]) if row["result"] is not None else None,
                 "error": row["error"]} for row in rows]

    def close(self):
        with self._lock:
            self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
