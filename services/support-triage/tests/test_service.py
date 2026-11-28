"""Service tests. No network and no real model: the model is a stub or the deterministic fake."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.gateway import Gateway
from app.handler import Deps
from sync_handle import handle
from app.helpdesk import InMemoryHelpdesk
from app.main import create_app
from evals.models import FakeModel
from evals.run import load_tickets

GOOD = json.dumps({"category": "billing", "priority": "high", "needs_human": True, "draft_reply": "Sorry about that."})
SECRET = "my card number is 4111 1111 1111 1111"


def make(complete=lambda s, u: GOOD, **kw) -> tuple[Deps, InMemoryHelpdesk]:
    h = InMemoryHelpdesk()
    return Deps(complete=complete, helpdesk=h, **kw), h


def boom(s, u):
    raise TimeoutError("slow")


class BrokenHelpdesk:
    def post_private_note(self, ticket_id, body):
        raise ConnectionError("down")


def test_happy_path_posts_private_note_and_logs_no_ticket_text(capsys):
    d, h = make()
    assert handle("t1", SECRET, d) == "posted"
    assert h.notes["t1"][0].startswith("[AI draft, not sent] category=billing priority=high")
    out = capsys.readouterr().out
    assert '"outcome": "posted"' in out and '"prompt_version": "v3"' in out
    assert "4111" not in out


def test_pii_is_masked_before_the_model_sees_it():
    seen = []
    d, _ = make(lambda s, u: seen.append(u) or GOOD)
    handle("t1", "Refund to 4111 1111 1111 1111, write to jo@example.com", d)
    assert seen == ["<ticket>Refund to [CARD], write to [EMAIL]</ticket>"]


@pytest.mark.parametrize("complete", [
    boom,
    lambda s, u: "Sure! billing",
    lambda s, u: json.dumps({"category": "hacked", "priority": "low", "needs_human": False}),
    lambda s, u: GOOD.replace("}", ', "extra": 1}'),
])
def test_every_fallback_writes_nothing(complete):
    d, h = make(complete)
    assert handle("t1", "hi", d) == "fallback"
    assert h.notes == {}


def test_helpdesk_failure_is_fallback_and_retry_works():
    d, _ = make()
    d.helpdesk = BrokenHelpdesk()
    assert handle("t1", "hi", d) == "fallback"
    d.helpdesk = InMemoryHelpdesk()
    assert handle("t1", "hi", d) == "posted"  # not marked seen after a failure


def test_kill_switch_is_a_noop():
    d, h = make(kill_switch=True)
    assert handle("t1", "hi", d) == "killed"
    assert h.notes == {}


def test_shadow_logs_but_posts_nothing_then_live_still_processes():
    d, h = make(shadow=True)
    assert handle("t1", "hi", d) == "shadow"
    assert h.notes == {}
    d.shadow = False
    assert handle("t1", "hi", d) == "posted"


def test_duplicate_delivery_does_nothing_twice():
    d, h = make()
    assert handle("t1", "hi", d) == "posted"
    assert handle("t1", "hi", d) == "duplicate"
    assert len(h.notes["t1"]) == 1


def test_gateway_client_speaks_openai_format():
    def respond(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert req.url.path == "/v1/chat/completions" and body["model"] == "triage-default"
        return httpx.Response(200, json={"choices": [{"message": {"content": GOOD}}]})

    g = Gateway("http://gw", "triage-default", client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    assert asyncio.run(g.complete("sys", "user")) == GOOD


def test_http_routes_and_env_kill_switch(monkeypatch):
    app = create_app()  # default deps; the gateway is never reached because the switch is on
    c = TestClient(app)
    assert c.get("/healthz").json() == {"ok": True}
    monkeypatch.setenv("KILL_SWITCH", "1")
    assert c.post("/webhook", json={"ticket_id": "t1", "text": "hi"}).json() == {"outcome": "killed"}
    assert c.post("/agent-action", json={"ticket_id": "t1", "action": "edited"}).status_code == 200
    assert c.post("/agent-action", json={"ticket_id": "t1", "action": "lol"}).status_code == 422


def test_golden_set_end_to_end_with_perfect_fake_model():
    """Same 50 tickets the evals use, through the whole service path."""
    tickets = load_tickets()
    by_text = {t["text"]: t for t in tickets}
    fake = FakeModel(accuracy=1.0)
    d, h = make(complete=lambda s, u: fake.predict(by_text[u.removeprefix("<ticket>").removesuffix("</ticket>")]).raw)
    assert {handle(t["id"], t["text"], d) for t in tickets} == {"posted"}
    for t in tickets:
        assert f"category={t['category']} priority={t['priority']}" in h.notes[t["id"]][0]
