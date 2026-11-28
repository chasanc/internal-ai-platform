"""Regression tests for the review findings: dedupe race, webhook secret, input bounds, strict schema, prompt sync."""
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.handler import PROMPT_VERSION, Deps
from sync_handle import handle
from app.helpdesk import InMemoryHelpdesk
from app.main import create_app
from evals.models import PROMPT_PATH
from evals.schema import parse_triage
from gateway.pii import mask

GOOD = json.dumps({"category": "billing", "priority": "high", "needs_human": True, "draft_reply": "Sorry."})


def test_in_flight_duplicate_is_not_posted_twice():
    entered, release = threading.Event(), threading.Event()

    def slow(system, user):
        entered.set()
        release.wait(5)
        return GOOD

    helpdesk = InMemoryHelpdesk()
    d = Deps(complete=slow, helpdesk=helpdesk)
    first: list[str] = []
    t = threading.Thread(target=lambda: first.append(handle("t1", "hello", d)))
    t.start()
    assert entered.wait(5)
    assert handle("t1", "hello", d) == "duplicate"  # same ticket while the first call is still in flight
    release.set()
    t.join(5)
    assert first == ["posted"]
    assert len(helpdesk.notes["t1"]) == 1


def test_failed_call_frees_the_claim_for_a_retry():
    calls = iter([TimeoutError("slow"), GOOD])

    def flaky(system, user):
        v = next(calls)
        if isinstance(v, Exception):
            raise v
        return v

    d = Deps(complete=flaky, helpdesk=InMemoryHelpdesk())
    assert handle("t1", "hello", d) == "fallback"
    assert handle("t1", "hello", d) == "posted"


def test_webhook_secret_required_when_set(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "s3cret")
    c = TestClient(create_app(Deps(complete=lambda s, u: GOOD, helpdesk=InMemoryHelpdesk())))
    body = {"ticket_id": "t1", "text": "hello"}
    assert c.post("/webhook", json=body).status_code == 401
    assert c.post("/webhook", json=body, headers={"X-Webhook-Secret": "wrong"}).status_code == 401
    assert c.post("/agent-action", json={"ticket_id": "t1", "action": "sent"}).status_code == 401
    assert c.post("/webhook", json=body, headers={"X-Webhook-Secret": "s3cret"}).json() == {"outcome": "posted"}


def test_open_only_with_explicit_insecure_local_opt_in():
    c = TestClient(create_app(Deps(complete=lambda s, u: GOOD, helpdesk=InMemoryHelpdesk())))  # conftest opts in
    assert c.post("/webhook", json={"ticket_id": "t1", "text": "hello"}).status_code == 200


@pytest.mark.parametrize("secret", [None, ""])
def test_no_secret_refuses_to_start_by_default(monkeypatch, secret):
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL")
    if secret is not None:
        monkeypatch.setenv("WEBHOOK_SECRET", secret)
    with pytest.raises(RuntimeError, match="WEBHOOK_SECRET"):  # injected deps do not bypass it either
        create_app(Deps(complete=lambda s, u: GOOD, helpdesk=InMemoryHelpdesk()))
    with pytest.raises(RuntimeError, match="WEBHOOK_SECRET"):
        create_app()


def test_a_secret_needs_no_opt_in(monkeypatch):
    monkeypatch.delenv("ALLOW_INSECURE_LOCAL")
    monkeypatch.setenv("WEBHOOK_SECRET", "s3cret")
    create_app(Deps(complete=lambda s, u: GOOD, helpdesk=InMemoryHelpdesk()))


def test_oversized_text_is_rejected():
    c = TestClient(create_app(Deps(complete=lambda s, u: GOOD, helpdesk=InMemoryHelpdesk())))
    assert c.post("/webhook", json={"ticket_id": "t1", "text": "a" * 20_001}).status_code == 422


def test_masker_stays_fast_on_long_input():
    t0 = time.perf_counter()
    mask("a" * 200_000)
    assert time.perf_counter() - t0 < 2


def test_schema_rejects_non_bool_needs_human():
    for bad in ('"yes"', '"true"', "1"):
        raw = '{"category":"billing","priority":"high","needs_human":%s,"draft_reply":""}' % bad
        assert parse_triage(raw) is None
    assert parse_triage(GOOD) is not None


def test_eval_and_service_use_the_same_prompt_version():
    assert PROMPT_PATH.name == f"triage.{PROMPT_VERSION}.md"
