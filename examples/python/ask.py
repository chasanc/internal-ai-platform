"""Call one tool through the model gateway, the way a real client should.

    uv run python -m examples.python.ask supplier-delay-triage "Storm closed the port, 2 days late."
    uv run python -m examples.python.ask finance-anomaly "INV-1 Hosting. Vendor HostNet (known). Amount 5,000." --dry-run

What it does, in order: mask PII (the gateway does not), send the tool's prompt as the system message and the text
wrapped in untrusted-data tags as the user message, call the tool's registry alias, then check the reply against the
tool's contract. Exit 0 = valid, 1 = invalid output (treat as the fallback path), 2 = the call failed.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import httpx
import yaml

from evals.schema import parse_triage
from evals.tools import load, parse
from gateway.pii import mask

ROOT = Path(__file__).parent.parent.parent
SUPPORT = "support-triage"  # a service with its own prompt and contract, not a folder under tools/


def tool_spec(tool: str):
    """(system prompt, tag that wraps untrusted text, validator for the raw reply)."""
    if tool == SUPPORT:
        prompt = (ROOT / "services/support-triage/prompts/triage.v3.md").read_text()
        return prompt, "ticket", lambda raw: parse_triage(raw) is not None
    prompt, contract, _ = load(tool)
    return prompt, "input", lambda raw: parse(raw, contract) is not None


def registry_alias(tool: str) -> str:
    """The first model alias the registry allows for this tool."""
    for path in (ROOT / "registry").glob("tier*/*.yaml"):
        entry = yaml.safe_load(path.read_text())
        if entry["name"] == tool:
            return entry["allowed_models"][0]
    raise SystemExit(f"{tool}: not in the registry")


def build_request(tool: str, text: str, alias: str) -> tuple[dict, int]:
    """Returns (request body, number of PII replacements)."""
    system, tag, _ = tool_spec(tool)
    masked, n = mask(text)
    body = {"model": alias, "temperature": 0, "max_tokens": 400,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": f"<{tag}>{masked}</{tag}>"}]}
    return body, n


def ask(tool: str, text: str, url: str, alias: str, key: str,
        client: httpx.Client | None = None) -> tuple[str, bool, int]:
    """Returns (raw reply, valid against the contract, PII replacements)."""
    body, n = build_request(tool, text, alias)
    r = (client or httpx).post(f"{url.rstrip('/')}/v1/chat/completions", json=body,
                               headers={"Authorization": f"Bearer {key}"}, timeout=60)
    r.raise_for_status()
    raw = r.json()["choices"][0]["message"]["content"] or ""
    return raw, tool_spec(tool)[2](raw), n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tool")
    ap.add_argument("text")
    ap.add_argument("--url", default=os.environ.get("GATEWAY_URL", "http://localhost:4000"))
    ap.add_argument("--alias", help="default: the first alias the registry allows for this tool")
    ap.add_argument("--dry-run", action="store_true", help="print the request, send nothing")
    a = ap.parse_args()
    alias = a.alias or registry_alias(a.tool)
    if a.dry_run:
        body, n = build_request(a.tool, a.text, alias)
        print(f"# {n} PII replacement(s); system prompt shortened for display")
        body["messages"][0]["content"] = body["messages"][0]["content"][:80] + "..."
        print(json.dumps(body, indent=1))
        return
    key = os.environ.get("GATEWAY_KEY", "sk-dev-only-master")  # in real use, the tool's own key from registry.issue_keys
    try:
        raw, valid, n = ask(a.tool, a.text, a.url, alias, key)
    except httpx.HTTPError as e:
        sys.exit(f"gateway call failed: {type(e).__name__}")
    print(f"alias={alias} pii_masked={n} valid={valid}\n{raw}")
    sys.exit(0 if valid else 1)


if __name__ == "__main__":
    main()
