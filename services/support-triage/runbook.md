# support-triage runbook

Classifies a ticket and writes an AI draft as a **private note**. It never replies to the customer. If anything fails it writes nothing and the ticket stays in the normal queue, so an outage costs speed, not correctness.

## Flow

webhook (`ticket_id`, `text`) -> kill switch? -> duplicate? -> gateway call -> strict parse -> private note.

| Outcome | Meaning | Ticket effect |
|---|---|---|
| `posted` | draft written | note added |
| `shadow` | ran and logged, nothing posted | none |
| `killed` | kill switch on | none |
| `duplicate` | same ticket id and prompt version already done | none |
| `fallback` | timeout, provider error, invalid output, or helpdesk error (see `reason` in the log) | none |

## Controls

- **Kill switch:** set `KILL_SWITCH=1`. Read on every request, so it works without a restart. Use it first when drafts look wrong.
- **Shadow mode:** `SHADOW_MODE=1` runs the model and logs results without posting. Use it to trial a new prompt or model on live traffic.
- **Model:** `MODEL_ALIAS` is a gateway alias. Change the model behind the alias in the gateway, after `make gate` passes.

## Real helpdesk and account context (both optional, off by default)

- **Helpdesk:** set `HELPDESK_URL`, `HELPDESK_USER`, `HELPDESK_TOKEN` and the note goes to that helpdesk as a non-public comment (`RestHelpdesk`). Unset, the in-memory fake is used. Not yet checked against a live helpdesk; for a different API replace that one class.
- **Account context:** set `CUSTOMER_DB_URL` (a Postgres URL for a read-only role) and install the extra: `pip install "psycopg[binary]"`. The webhook may then carry `requester_email`; the service looks up plan, order status and last invoice from the view `support_customer_context` (columns `email` lower-cased, `plan`, `order_status`, `invoice_number`, `invoice_date`, `invoice_amount`, `invoice_status`; the database owner creates it and its unique email). The email never goes to the model, the logs or the note. No match, several matches or an error means the draft uses the ticket text alone. A drafted note with account data tells the agent to verify the sender first. Prompt v3 tells the model how to use the account line (priority and needs_human only, never copied into the draft). v3 was evaluated on 2026-11-27 (ADR 0001): golden set on four models, haiku on the account set (`account_leaks` 0 of 12, one invalid reply) and the held-out set. Those calls went straight to the providers, not through the gateway or the lookup, so trial the lookup in shadow mode before going live. To re-run: `make eval MODEL=...` and `uv run python -m evals.run MODEL --dataset evals/datasets/support-triage.account.jsonl --out ...` (`account_leaks` must stay 0). Going from v2 to v3 also lets each ticket be processed once more, because the duplicate key includes the prompt version.
- The triage log line gains `account`: `off`, `found`, `none` or `error`.

## Logs

JSON lines. `triage` events carry `ticket_id`, `prompt_version`, `model`, `outcome`, and for posted or shadow the category, priority and needs_human. `agent_action` events (`sent`, `edited`, `discarded`) come from `POST /agent-action`. Ticket text is never logged. `triage` events also carry `duration_ms` (whole request). To read them: `docker compose logs --no-log-prefix support-triage > triage.log`, then `python scripts/telemetry_report.py triage.log [--since-minutes 60] [--spend spend.json]`. It prints agent action rates and report coverage per prompt version, fallback rate and reasons, latency p50/p95, and cost per tool key; it exits 1 when the fallback rate is above 5% (over at least 20 tickets) or the kill switch was used.

## Alerts to set up in deployment

- `fallback` rate above 5% over 15 minutes: gateway or model problem. Check `reason`.
- `discarded` rate rising week on week: draft quality is slipping. Re-run the evals.

## Changing the prompt or model

1. Edit the prompt or alias. 2. `make eval MODEL=...` and commit `evals/results/candidate.json`. 3. `make gate`. CI blocks the PR without a candidate result. 4. Trial in shadow mode, then go live.

## Known limits

- Idempotency is in memory by default and resets on restart, so a redelivery after a restart can post a second note. Set `IDEMPOTENCY_DB=/path/claims.db` for the SQLite store (restart-safe, shared by workers on one machine). A claim never expires: if a worker dies mid-call, delete that row. Use the database across machines.
- The service will not start without `WEBHOOK_SECRET` (set `ALLOW_INSECURE_LOCAL=1` for local development only).
- The helpdesk adapter is an in-memory fake. Implement `post_private_note` for the real helpdesk.
