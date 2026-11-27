import json
import sys
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.gateway import Gateway  # noqa: E402
from app.main import create_app  # noqa: E402


def test_healthz():
    assert TestClient(create_app()).get("/healthz").json() == {"ok": True}


def test_gateway_sends_alias_and_returns_text():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    g = Gateway("http://gw/", "triage-default", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert g.complete("sys", "user") == "hi"
    assert seen["body"]["model"] == "triage-default"
