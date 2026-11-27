import json
import threading

import pytest

from app.handler import PROMPT_VERSION, Deps, handle
from app.helpdesk import InMemoryHelpdesk
from app.idempotency import InMemoryIdempotencyStore, SQLiteIdempotencyStore

GOOD = json.dumps({"category": "billing", "priority": "high", "needs_human": True, "draft_reply": "Sorry."})


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    return InMemoryIdempotencyStore() if request.param == "memory" else SQLiteIdempotencyStore(str(tmp_path / "c.db"))


def test_claim_is_exclusive_until_released(store):
    assert store.claim("a") and not store.claim("a")
    assert store.claim("b")  # other keys are independent
    store.release("a")
    assert store.claim("a")
    store.release("never-claimed")  # releasing an unknown key is harmless


def test_exactly_one_of_many_concurrent_claims_wins(store):
    wins, barrier = [], threading.Barrier(16)

    def go():
        barrier.wait()
        wins.append(store.claim("k"))

    threads = [threading.Thread(target=go) for _ in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert wins.count(True) == 1


def test_sqlite_claims_survive_a_restart_and_are_shared(tmp_path):
    path = str(tmp_path / "c.db")
    assert SQLiteIdempotencyStore(path).claim("t1:v2")
    assert not SQLiteIdempotencyStore(path).claim("t1:v2")  # a new instance is a restarted or second worker


def test_handler_posts_once_across_restarts(tmp_path):
    h, path = InMemoryHelpdesk(), str(tmp_path / "c.db")
    first = Deps(complete=lambda s, u: GOOD, helpdesk=h, idempotency=SQLiteIdempotencyStore(path))
    restarted = Deps(complete=lambda s, u: GOOD, helpdesk=h, idempotency=SQLiteIdempotencyStore(path))
    assert handle("t1", "hi", first) == "posted"
    assert handle("t1", "hi", restarted) == "duplicate" and len(h.notes["t1"]) == 1


@pytest.mark.parametrize("failure", ["exception", "invalid", "shadow"])
def test_claim_is_released_after_any_non_posted_outcome(store, failure):
    def complete(s, u):
        if failure == "exception":
            raise TimeoutError
        return "not json" if failure == "invalid" else GOOD

    h = InMemoryHelpdesk()
    d = Deps(complete=complete, helpdesk=h, idempotency=store, shadow=failure == "shadow")
    assert handle("t1", "hi", d) in {"fallback", "shadow"}
    assert store.claim(f"t1:{PROMPT_VERSION}")  # released, so a retry or going live can process the ticket again
