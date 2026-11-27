import os

import hmac

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.gateway import Gateway
from app.handler import Deps, handle, record_action
from app.customer import PostgresCustomerLookup
from app.helpdesk import Helpdesk, InMemoryHelpdesk, RestHelpdesk
from app.idempotency import InMemoryIdempotencyStore, SQLiteIdempotencyStore


class Webhook(BaseModel):
    ticket_id: str = Field(max_length=128)
    text: str = Field(max_length=20_000)  # bounds regex work in the PII masker
    requester_email: str | None = Field(default=None, max_length=320)  # lookup key only; never logged or sent on


class AgentAction(BaseModel):
    ticket_id: str = Field(max_length=128)
    action: str = Field(max_length=32)


def flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in {"1", "true", "yes"}


def helpdesk_from_env() -> Helpdesk:
    """HELPDESK_URL selects the real adapter and then needs the user and token too; unset means the in-memory fake."""
    if not os.environ.get("HELPDESK_URL"):
        return InMemoryHelpdesk()
    return RestHelpdesk(os.environ["HELPDESK_URL"], os.environ["HELPDESK_USER"], os.environ["HELPDESK_TOKEN"])


def create_app(deps: Deps | None = None) -> FastAPI:
    d = deps or Deps(
        complete=Gateway(os.environ.get("GATEWAY_URL", "http://gateway:4000"),
                         os.environ.get("MODEL_ALIAS", "triage-default"),
                         os.environ.get("GATEWAY_KEY", "")).complete,
        helpdesk=helpdesk_from_env(),
        lookup=PostgresCustomerLookup(os.environ["CUSTOMER_DB_URL"]) if os.environ.get("CUSTOMER_DB_URL") else None,
        model=os.environ.get("MODEL_ALIAS", "triage-default"),
        idempotency=SQLiteIdempotencyStore(os.environ["IDEMPOTENCY_DB"]) if os.environ.get("IDEMPOTENCY_DB")
        else InMemoryIdempotencyStore(),  # a file path makes duplicate protection survive restarts and share across workers
    )
    secret = os.environ.get("WEBHOOK_SECRET", "")  # shortcut: shared secret, no body signature or replay window
    if not secret and not flag("ALLOW_INSECURE_LOCAL"):  # fail closed: no secret means no service, not an open one
        raise RuntimeError("WEBHOOK_SECRET is not set; set it, or set ALLOW_INSECURE_LOCAL=1 for local development only")

    def require_secret(x_webhook_secret: str = Header(default="")) -> None:
        if secret and not hmac.compare_digest(x_webhook_secret, secret):
            raise HTTPException(401, "bad or missing X-Webhook-Secret")

    app = FastAPI(title="support-triage")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.post("/webhook", dependencies=[Depends(require_secret)])
    def webhook(w: Webhook):
        if deps is None:  # env flags are read per request so the kill switch works without a restart
            d.kill_switch, d.shadow = flag("KILL_SWITCH"), flag("SHADOW_MODE")
        return {"outcome": handle(w.ticket_id, w.text, d, w.requester_email)}

    @app.post("/agent-action", dependencies=[Depends(require_secret)])
    def agent_action(a: AgentAction):
        if not record_action(a.ticket_id, a.action):
            raise HTTPException(422, "action must be sent, edited or discarded")
        return {"ok": True}

    return app
