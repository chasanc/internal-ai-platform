# ADR 0005: One fallback path: on any doubt, write nothing

Status: accepted (2026-11-27).

## Context

The triage service sits between a helpdesk and a model. The model can time out, return invalid JSON, return an unknown category, or be steered by ticket text. Many special cases would each need their own handling and tests.

## Decision

All failures take **one path**: log it without ticket text, leave the ticket untouched for a human, and write nothing. This covers gateway errors, timeouts, invalid output and out-of-contract values.

Around it:

- The service only adds **private-note drafts**; it never replies to a customer or changes ticket state.
- A **kill switch** is read on every request, so it works without a restart.
- **Shadow mode** runs the full flow but writes nothing and does not mark the ticket as seen.
- **Idempotency** is keyed on (ticket id, prompt version), so a retried webhook does not post twice.
- Agent actions (sent, edited, discarded) are logged per prompt version as the live quality signal.

## Why

- One path is easy to reason about, test (each failure mode has a test) and explain.
- Doing nothing is the safe state: the ticket still reaches a person as before.
- It makes the model a helper, not a dependency: an outage costs time saved, not correctness.

## Consequences

- Failed tickets get no draft and no retry queue; a person handles them. A retry with backoff can be added later without changing the contract.
- Idempotency sits behind a small store interface (`app/idempotency.py`). The default is in memory and resets on restart; set `IDEMPOTENCY_DB` to a file path to use the SQLite store, which survives restarts and is shared by workers on one machine. A claim never expires, so a worker killed mid-call blocks that ticket until its row is deleted. A duplicate private note is the worst case; use the database when running across machines.
- The service refuses to start without `WEBHOOK_SECRET`. `ALLOW_INSECURE_LOCAL=1` opts out for local development only.
