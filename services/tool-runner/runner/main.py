"""Run one registered tool on a piece of text: POST /run/{tool}. For an automation platform that crawls and delivers.

Mask the text, call the tool's gateway alias with the tool's own key, check the reply against the tool's contract.
200 = validated JSON. 422 = the model answered but broke the contract. 502 = the call failed. The caller branches on the
status (skip, or tell a person); this service never retries and never writes anywhere.
"""
import hmac
import json
import os
import re
import time
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from evals.tools import load, parse
from gateway.pii import mask

ROOT = Path(__file__).parent.parent.parent.parent
TAGS = re.compile(r"</?\s*input\b[^>]*>", re.I)  # the page text must not be able to close the data wrapper


class Run(BaseModel):
    text: str = Field(max_length=20_000)  # bounds regex work in the masker and the model bill


def log(**fields) -> None:
    print(json.dumps({"ts": time.time(), "event": "run", **fields}), flush=True)  # counts and ids only, never text


def registry_alias(tool: str, root: Path = ROOT) -> str:
    for path in (root / "registry").glob("tier*/*.yaml"):
        entry = yaml.safe_load(path.read_text())
        if entry["name"] == tool:
            return entry["allowed_models"][0]
    raise RuntimeError(f"{tool}: not in the registry")


def key_for(tool: str) -> str:
    """One gateway key per tool (GATEWAY_KEY_COMPETITOR_DIGEST), so spend and revocation stay per tool."""
    return os.environ.get("GATEWAY_KEY_" + tool.upper().replace("-", "_")) or os.environ.get("GATEWAY_KEY", "")


def create_app(client: httpx.AsyncClient | None = None) -> FastAPI:
    secret = os.environ.get("RUN_SECRET", "")  # shortcut: shared secret, no replay window and no rate limit
    if not secret and os.environ.get("ALLOW_INSECURE_LOCAL", "").lower() not in {"1", "true", "yes"}:
        raise RuntimeError("RUN_SECRET is not set; set it, or set ALLOW_INSECURE_LOCAL=1 for local development only")
    url = os.environ.get("GATEWAY_URL", "http://gateway:4000").rstrip("/")
    tools = {t.strip() for t in os.environ.get("RUN_TOOLS", "competitor-digest").split(",") if t.strip()}
    loaded = {t: (*load(t)[:2], registry_alias(t)) for t in tools}  # fails at start if a tool or alias is missing
    http = client or httpx.AsyncClient()
    app = FastAPI(title="tool-runner")

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "tools": sorted(tools)}

    @app.post("/run/{tool}")
    async def run(tool: str, body: Run, x_run_secret: str = Header(default="")):
        if secret and not hmac.compare_digest(x_run_secret, secret):
            raise HTTPException(401, "bad or missing X-Run-Secret")
        if tool not in loaded:
            raise HTTPException(404, "unknown tool")
        prompt, contract, alias = loaded[tool]
        t0 = time.perf_counter()

        def done(outcome: str, **fields) -> None:
            log(tool=tool, outcome=outcome, duration_ms=round((time.perf_counter() - t0) * 1000), **fields)

        masked, n = mask(TAGS.sub("", body.text))
        try:
            r = await http.post(f"{url}/v1/chat/completions", timeout=30, json={
                "model": alias, "temperature": 0, "max_tokens": 400,
                "messages": [{"role": "system", "content": prompt},
                             {"role": "user", "content": f"<input>{masked}</input>"}]},
                headers={"Authorization": f"Bearer {key_for(tool)}"} if key_for(tool) else {})
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"] or ""
        except Exception as e:  # timeout, provider error, or an unexpected reply shape
            done("failed", reason=type(e).__name__, pii_masked=n)
            raise HTTPException(502, "model call failed")
        if parse(raw, contract) is None:
            done("invalid_output", pii_masked=n)
            raise HTTPException(422, "model reply did not match the tool contract")
        done("ok", pii_masked=n)
        return json.loads(raw)

    return app
