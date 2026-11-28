"""Check the multi-instance stack: the same ticket sent many times at once must be posted exactly once.

    python scripts/smoke_ha.py [URL]        (after: make up-ha)

The requests go through the load balancer, so they land on both triage instances; only the shared claims table in
Postgres can make exactly one of them win. Mock model, no cost.
"""
import asyncio
import os
import sys
import uuid
from collections import Counter

import httpx

url = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
secret = os.environ.get("WEBHOOK_SECRET", "dev-only-webhook-secret")  # same default as docker-compose.yml


async def main() -> int:
    ticket = {"ticket_id": f"ha-{uuid.uuid4().hex[:8]}", "text": "I was charged twice. Please refund."}
    async with httpx.AsyncClient(timeout=60) as c:
        for _ in range(30):  # wait up to 60 s for both instances and the balancer
            try:
                if (await c.get(f"{url}/healthz")).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2)
        else:
            print(f"smoke-ha: {url} never became healthy")
            return 2
        rs = await asyncio.gather(*(c.post(f"{url}/webhook", json=ticket, headers={"X-Webhook-Secret": secret})
                                    for _ in range(12)))
    outcomes = Counter(r.json().get("outcome") if r.status_code == 200 else f"http {r.status_code}" for r in rs)
    print(f"smoke-ha: {dict(outcomes)}")
    return 0 if outcomes == {"posted": 1, "duplicate": 11} else 1


sys.exit(asyncio.run(main()))
