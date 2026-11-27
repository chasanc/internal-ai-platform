# python-service template

Starting point for a new AI tool. Copy it to `services/<name>/`, then:

1. Add your logic beside `app/main.py` (see `services/support-triage/` for a full example).
2. Call models only through `app/gateway.py` with a gateway alias. It speaks the OpenAI-compatible API, so the gateway can change models without touching the tool.
3. Log with `app/logs.py`: ids, versions and outcomes only, never request or ticket text.
4. Keep the prompt in `prompts/` and version it. A prompt change needs a new eval result in the same PR (CI enforces this).
5. Add a registry entry (`registry/`) with an owner, data class and runbook.

Includes: health endpoint, gateway client, structured logging, non-root Dockerfile.
