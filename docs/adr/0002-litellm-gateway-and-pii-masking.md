# ADR 0002: LiteLLM as the gateway; PII masking in the service

Status: accepted (2026-11-27).

## Context

Every tool needs model access with keys, budgets, a fallback and no prompt logging. Options: each service calls providers directly, we build a gateway, or we run an existing proxy.

## Decision

- Run **LiteLLM as the gateway**. Services call aliases (`triage-default`, `drafts-default`, `analysis-default`), never provider model names. Config is one file: `gateway/litellm.config.yaml`.
- One retry and **one fallback** per alias. Message logging is off. Provider keys are read from the environment only.
- **PII and financial-id masking happens twice.** The service masks first (`gateway/pii.py`, used by support-triage), so raw text never leaves it. The gateway then masks every request again with a LiteLLM pre-call hook (`gateway/mask_hook.py`), which covers callers that do not mask: other languages, curl, a new tool. Masking is idempotent, so the second pass is harmless. The hook masks user, assistant and tool messages (not the system prompt) and rejects the request if masking fails.

## Why

- A maintained proxy gives per-key budgets, routing and provider coverage that we would otherwise rebuild and then maintain.
- Aliases let us swap a model with a config change and an eval run, not a code change.
- Masking in the service keeps raw personal data inside the service boundary: the gateway, its database and its logs never see it. A gateway-side masker alone would protect every caller, but it receives the raw text first and does not know which fields matter to each tool. So the service mask is the primary layer and the gateway hook is the safety net. A caller that skips the service mask still has raw text reach the gateway process (message logging is off), but not the provider.

## Why not a custom gateway

It would reproduce routing, budgets and key management for no benefit at this scale. We keep the option open: services only know the OpenAI-style interface.

## Consequences

- The masker is regex-based: email, card (Luhn), phone, address, IBAN (mod-97), account and routing numbers after a keyword, SWIFT/BIC after a keyword, US tax id. Names, free-form addresses and bare account numbers with no keyword pass through. Amounts, invoice numbers and vendor names are never masked, because the finance tool needs them. Presidio or similar is the next step if a tool needs it.
- Every request is masked at the gateway even if the caller forgot. Tools that handle personal data should still mask in the service so the gateway never holds raw text.
- The hook adds a regex pass to each request. It is not a filter on replies: model output is not masked.
