"""The handler is async: slow model calls overlap, and shared-store claims work across instances."""
import asyncio
import json
import time

from app.handler import Deps, handle
from app.helpdesk import InMemoryHelpdesk
from app.idempotency import InMemoryIdempotencyStore, PostgresIdempotencyStore

GOOD = json.dumps({"category": "billing", "priority": "high", "needs_human": True, "draft_reply": "Sorry."})


class FakeConn:
    """Stands in for psycopg: just enough of the claims table to check the wiring, commit and close."""
    rows: dict[str, float] = {}
    now = 1000.0
    closed = 0

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        FakeConn.closed += 1

    def execute(self, sql, params=()):
        self.rowcount = 0
        if sql.startswith("INSERT"):
            key, ttl = params
            if key not in self.rows or self.rows[key] < self.now - ttl:
                self.rows[key] = self.now
                self.rowcount = 1
        elif sql.startswith("DELETE"):
            self.rows.pop(params[0], None)


def test_slow_model_calls_overlap_instead_of_queueing():
    async def slow(system, user):
        await asyncio.sleep(0.2)
        return GOOD

    d = Deps(complete=slow, helpdesk=InMemoryHelpdesk())

    async def go():
        return await asyncio.gather(*(handle(f"t{i}", "hi", d) for i in range(20)))

    t0 = time.perf_counter()
    assert set(asyncio.run(go())) == {"posted"}
    assert time.perf_counter() - t0 < 1.0  # 20 x 0.2 s one after another would be 4 s


def test_two_instances_sharing_a_store_post_a_ticket_once():
    shared = InMemoryIdempotencyStore()  # stands in for the Postgres table both instances use
    helpdesks = [InMemoryHelpdesk(), InMemoryHelpdesk()]

    async def slow(system, user):
        await asyncio.sleep(0.1)
        return GOOD

    async def go():
        ds = [Deps(complete=slow, helpdesk=h, idempotency=shared) for h in helpdesks]
        return await asyncio.gather(*(handle("t1", "hi", ds[i % 2]) for i in range(10)))

    outcomes = asyncio.run(go())
    assert sorted(outcomes) == ["duplicate"] * 9 + ["posted"]
    assert sum(len(h.notes.get("t1", [])) for h in helpdesks) == 1


def test_postgres_store_claims_once_releases_and_takes_over_stale_claims():
    FakeConn.rows.clear()
    store = PostgresIdempotencyStore(connect=FakeConn, ttl_s=600)
    assert store.claim("t1:v3") and not store.claim("t1:v3")
    store.release("t1:v3")
    assert store.claim("t1:v3")
    FakeConn.now += 601  # the instance that held it died without releasing
    assert store.claim("t1:v3")
    assert FakeConn.closed >= 5  # every call closes its connection
