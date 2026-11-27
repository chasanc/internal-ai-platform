# tool-runner

`POST /run/{tool}` for an automation platform that crawls or collects text and delivers the result. It masks PII, calls the tool's gateway alias with the tool's own key, and checks the reply against the tool's `contract.json`. It never writes anywhere and never retries.

| Status | Meaning | What the automation should do |
|---|---|---|
| 200 | Reply matches the contract; body is the JSON | Deliver it |
| 401 | Missing or wrong `X-Run-Secret` | Fix the secret |
| 404 | Tool is not in `RUN_TOOLS` | Fix the URL |
| 422 | Model answered but broke the contract (or text over 20,000 chars) | Skip this item; do not deliver |
| 502 | Gateway call failed or timed out | Skip, and tell a person if it keeps happening |

## Wiring the automation platform

1. Add an HTTP/webhook step: `POST https://<runner>/run/competitor-digest`, header `X-Run-Secret: <secret>`, JSON body `{"text": "<crawled page text>"}`.
2. Add a filter after it that continues only when the response status is 200. Without it a 422 or 502 flows on as if it were a digest.
3. Deliver `digest` to the channel, and use `notable` to decide who gets pinged.

The runner only summarises; the crawl, its schedule and the delivery live in the automation platform.

## Config

| Variable | Purpose |
|---|---|
| `RUN_SECRET` | Shared secret. Required; `ALLOW_INSECURE_LOCAL=1` is the local-only opt-out |
| `GATEWAY_URL` | Default `http://gateway:4000` |
| `GATEWAY_KEY_COMPETITOR_DIGEST` | One key per tool, so spend and revocation stay per tool. `GATEWAY_KEY` is the fallback |
| `RUN_TOOLS` | Comma-separated tools to serve. Default `competitor-digest` |

Logs are JSON lines with tool, outcome, `duration_ms` and the PII count; never the text.

## Limits

No rate limit and no replay window: one shared secret, so put it behind the platform's network controls. Tested against a stub gateway only; no real model has run through it.
