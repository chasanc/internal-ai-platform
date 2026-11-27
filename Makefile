BASELINE  ?= evals/baselines/support-triage.json
CANDIDATE ?= evals/results/candidate.json
MODEL     ?=
MAX_SPEND ?= 0.50

COMPOSE      = docker compose
REAL_COMPOSE = docker compose -f docker-compose.yml -f docker-compose.real.yml
REAL_GUARD   = @test "$(CONFIRM_REAL_AI)" = yes || (echo "refusing: this makes real, paid model calls. Add CONFIRM_REAL_AI=yes"; exit 2)

.PHONY: test eval gate up smoke down up-real smoke-real

test:
	uv run pytest -q

# Real-model run (needs keys in .env): make eval MODEL=anthropic/<dated-model>
eval:
	@test -n "$(MODEL)" || (echo "usage: make eval MODEL=<litellm model>"; exit 2)
	uv run python -m evals.run $(MODEL) --max-spend $(MAX_SPEND) --out $(CANDIDATE)

# Local stack with real AI OFF (mock alias, no provider keys in the containers).
up:
	$(COMPOSE) up -d --build

smoke:
	uv run python scripts/smoke.py http://localhost:8000

down:
	$(COMPOSE) down -v

# The ONE real check before a release: one ticket, one real call. Needs keys in .env.
# Usage: make down up-real smoke-real CONFIRM_REAL_AI=yes
up-real:
	$(REAL_GUARD)
	$(REAL_COMPOSE) up -d --build

smoke-real:
	$(REAL_GUARD)
	uv run python scripts/smoke.py http://localhost:8000

# Gate a candidate against the baseline. With no candidate, the baseline is checked against its own floors.
gate:
	uv run python -m evals.gate $(if $(wildcard $(CANDIDATE)),$(CANDIDATE),$(BASELINE)) $(BASELINE)
