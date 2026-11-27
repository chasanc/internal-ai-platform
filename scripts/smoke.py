"""Send ONE ticket through a running stack and check the service handled it.

    python scripts/smoke.py [URL]

Whether the call is real or mocked depends on the stack (see docker-compose.real.yml), not on this script.
"""
import os
import sys
import time
import uuid

import httpx

url = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")

for _ in range(30):  # wait up to 60 s for the stack
    try:
        if httpx.get(f"{url}/healthz", timeout=2).status_code == 200:
            break
    except httpx.HTTPError:
        pass
    time.sleep(2)
else:
    sys.exit(f"smoke: {url} never became healthy")

def _env_file_value(name: str) -> str | None:  # compose reads .env, so the smoke test must see the same value
    try:
        for line in open(".env"):
            key, _, value = line.strip().partition("=")
            if key == name and value:
                return value
    except FileNotFoundError:
        pass
    return None


secret = os.environ.get("WEBHOOK_SECRET") or _env_file_value("WEBHOOK_SECRET") or "dev-only-webhook-secret"  # default matches docker-compose.yml
ticket = {"ticket_id": f"smoke-{uuid.uuid4().hex[:8]}",
          "text": "I was charged twice for my subscription. Please refund the duplicate."}

probe = httpx.post(f"{url}/webhook", json=ticket, timeout=60)  # no secret: a secured stack must refuse
print(f"smoke: webhook without secret -> http {probe.status_code} ({'secured' if probe.status_code == 401 else 'OPEN'})")
if probe.status_code == 200:  # an open stack handled it; use a fresh id so the real call below is not a duplicate
    ticket["ticket_id"] = f"smoke-{uuid.uuid4().hex[:8]}"

r = httpx.post(f"{url}/webhook", json=ticket, headers={"X-Webhook-Secret": secret}, timeout=60)
outcome = r.json().get("outcome") if r.status_code == 200 else f"http {r.status_code}"
print(f"smoke: outcome={outcome}")
sys.exit(0 if outcome in {"posted", "shadow"} else 1)  # fallback means the gateway or model failed
