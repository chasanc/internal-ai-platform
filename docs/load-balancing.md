# Running several instances behind a load balancer

`make up-ha smoke-ha` starts two gateways and two triage services behind nginx, with one Postgres and one Redis, and checks that 12 simultaneous copies of one ticket are posted once. It uses the mock model, so it costs nothing. `make down` removes it.

## What is shared, and why

| Piece | Shared how | If it were per instance |
|---|---|---|
| Gateway keys, budgets, spend | One Postgres (`DATABASE_URL`) | Keys would differ per instance |
| Gateway schema | One `migrate` job; instances run with `DISABLE_SCHEMA_UPDATE=true` | Instances starting together would race the migration |
| Gateway rate limits and provider cooldowns | Redis, one `REDIS_URL` (`redis://[:password@]host:port`, `rediss://` for TLS); unset means per instance | A 60 requests/minute key would allow 60 per instance, and each instance would find a provider outage on its own |
| Triage duplicate protection | `IDEMPOTENCY_DB_URL`: a `claims` table in a Postgres database of its own | The same ticket could be answered once per instance |
| Tool runner | Nothing: it keeps no state | Scale freely |

The triage claims live in their own database (`triage`) because the gateway owns and migrates `litellm`. A claim older than 10 minutes counts as abandoned, so an instance that dies mid-request cannot block a ticket for ever. Keep that TTL above the slowest possible request.

## Async

Both services are async. The model call is awaited, so one instance holds many slow calls at once. The helpdesk, customer lookup and claim store are blocking libraries, so each runs in a worker thread instead of stalling the event loop. Their connections are opened per call, so there is no pool to share between instances.

## Limits

- Gateway budgets are not hard caps across instances. Spend is written to Postgres in batches, so a budget can overshoot by a few requests per instance. Not measured here.
- To use a Redis outside the stack, set `REDIS_URL` in `.env` (read by `make up-ha` only). It is tested with and without a password against the local Redis; `rediss://` and a managed Redis are not. The password sits inside the URL, so keep `.env` out of git.
- The nginx file is a local stand-in. In the cloud use the platform's balancer, with `/health/liveliness` for the gateway and `/healthz` for the services.
- The helpdesk in this stack is the in-memory fake, so "posted" means one instance accepted the ticket, not that a real helpdesk got it.
- Postgres, Redis and the balancer are single points of failure here. High availability for those is the platform's job.
