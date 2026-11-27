"""Every example client call works against a stub gateway: right alias, prompt, untrusted-data wrapping, PII masked."""
import json

import httpx
import pytest

from evals.tools import load
from examples.python.ask import SUPPORT, ask, build_request, registry_alias

TOOLS = ["pr-risk-summary", "marketing-campaign-brief", "competitor-digest", "finance-anomaly", "hr-jd-drafts",
         "supplier-delay-triage", SUPPORT]
SUPPORT_REPLY = {"category": "billing", "priority": "high", "needs_human": True, "draft_reply": "Sorry."}


def good_reply(tool: str) -> str:
    if tool == SUPPORT:
        return json.dumps(SUPPORT_REPLY)
    _, contract, golden = load(tool)
    return json.dumps({**golden[0]["expected"], **{k: "text" for k in contract["text"]}})


def stub_gateway(tool: str, seen: list) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers["authorization"], json.loads(request.content)))
        return httpx.Response(200, json={"choices": [{"message": {"content": good_reply(tool)}}]})
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("tool", TOOLS)
def test_example_call(tool):
    seen: list = []
    raw, valid, n = ask(tool, "Contact jane@example.com about this.", "http://gw:4000",
                        registry_alias(tool), "sk-test", stub_gateway(tool, seen))
    path, auth, body = seen[0]
    assert valid and raw == good_reply(tool)
    assert (path, auth) == ("/v1/chat/completions", "Bearer sk-test")
    assert body["model"] == registry_alias(tool)
    tag = "ticket" if tool == SUPPORT else "input"
    user = body["messages"][1]["content"]
    assert user.startswith(f"<{tag}>") and user.endswith(f"</{tag}>")
    assert "jane@example.com" not in user and "[EMAIL]" in user and n == 1


@pytest.mark.parametrize("tool", TOOLS)
def test_invalid_reply_is_reported(tool):
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "sure, here you go"}}]})))
    assert ask(tool, "hello", "http://gw:4000", registry_alias(tool), "k", client)[1] is False


def test_every_registry_tool_has_an_example():
    from registry.issue_keys import load_tools
    assert {t["name"] for t in load_tools()} == set(TOOLS)


def test_request_uses_the_tools_own_prompt():
    body, _ = build_request("finance-anomaly", "x", "analysis-default")
    assert body["messages"][0]["content"] == load("finance-anomaly")[0]
