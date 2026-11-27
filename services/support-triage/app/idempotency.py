"""Idempotency store: one claim per (ticket id, prompt version), taken before the model call.

claim() is atomic: of two concurrent callers with the same key exactly one gets True. release() frees a claim after a
non-posted outcome so a retry can run. Two implementations, both stdlib only:
- InMemoryIdempotencyStore: one process; forgets everything on restart.
- SQLiteIdempotencyStore: survives restarts and is shared by workers on one machine (a file on a shared volume).
shortcut: a claim never expires, so a worker killed between claim and release leaves that ticket blocked until its row
is deleted; add a timestamp and a TTL for in-flight claims, or use the database, when that matters.
"""
import sqlite3
import threading
from typing import Protocol


class IdempotencyStore(Protocol):
    def claim(self, key: str) -> bool: ...
    def release(self, key: str) -> None: ...


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: set[str] = set()

    def claim(self, key: str) -> bool:
        with self._lock:
            if key in self._seen:
                return False
            self._seen.add(key)
            return True

    def release(self, key: str) -> None:
        with self._lock:
            self._seen.discard(key)


class SQLiteIdempotencyStore:
    def __init__(self, path: str) -> None:
        self.path = path
        with self._connect() as c:
            c.execute("PRAGMA journal_mode=WAL")  # readers do not block the writer across worker processes
            c.execute("CREATE TABLE IF NOT EXISTS claims (key TEXT PRIMARY KEY)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)  # a connection per call: safe across threads and processes

    def claim(self, key: str) -> bool:
        c = self._connect()
        try:
            with c:  # commits on success
                return c.execute("INSERT OR IGNORE INTO claims VALUES (?)", (key,)).rowcount == 1
        finally:
            c.close()

    def release(self, key: str) -> None:
        c = self._connect()
        try:
            with c:
                c.execute("DELETE FROM claims WHERE key = ?", (key,))
        finally:
            c.close()
