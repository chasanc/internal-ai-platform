"""Idempotency store: one claim per (ticket id, prompt version), taken before the model call.

claim() is atomic: of two concurrent callers with the same key exactly one gets True. release() frees a claim after a
non-posted outcome so a retry can run. Two implementations, both stdlib only:
- InMemoryIdempotencyStore: one process; forgets everything on restart.
- SQLiteIdempotencyStore: survives restarts and is shared by workers on one machine (a file on a shared volume).
- PostgresIdempotencyStore: shared by every instance behind a load balancer; abandoned claims expire.
shortcut: the in-memory and SQLite claims never expire, so a worker killed between claim and release leaves that
ticket blocked until its row is deleted; behind a load balancer use the Postgres store.
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


class PostgresIdempotencyStore:
    """Shared by every instance behind a load balancer. One short-lived connection per call; `connect` is injectable.

    A claim older than `ttl_s` counts as abandoned (its instance died between claim and release) and is taken over,
    so a crashed instance cannot block a ticket for ever. Keep ttl_s above the longest possible request.
    Use a database of its own, not the gateway's: the gateway owns and migrates that one.
    """

    def __init__(self, dsn: str = "", connect=None, ttl_s: int = 600):
        if connect is None:
            import psycopg  # optional dependency: pip install "psycopg[binary]"
            connect = lambda: psycopg.connect(dsn, connect_timeout=5)  # noqa: E731
        self.connect, self.ttl_s = connect, ttl_s
        with self._tx() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(7301)")  # instances starting together must not race the CREATE
            cur.execute("CREATE TABLE IF NOT EXISTS claims (key TEXT PRIMARY KEY, claimed_at TIMESTAMPTZ NOT NULL)")

    def _tx(self):
        from contextlib import contextmanager

        @contextmanager
        def tx():
            conn = self.connect()
            try:
                with conn:  # commits on success, rolls back on error
                    yield conn.cursor()
            finally:
                conn.close()
        return tx()

    def claim(self, key: str) -> bool:
        with self._tx() as cur:  # inserts, or takes over a stale claim; a live claim matches neither, so 0 rows
            cur.execute("INSERT INTO claims (key, claimed_at) VALUES (%s, now()) ON CONFLICT (key) DO UPDATE "
                        "SET claimed_at = now() WHERE claims.claimed_at < now() - make_interval(secs => %s)",
                        (key, self.ttl_s))
            return cur.rowcount == 1

    def release(self, key: str) -> None:
        with self._tx() as cur:
            cur.execute("DELETE FROM claims WHERE key = %s", (key,))


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
