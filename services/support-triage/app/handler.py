"""Triage one ticket. Any failure takes the single fallback path: write nothing, ticket stays in the normal queue."""
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.customer import CustomerLookup
from app.helpdesk import Helpdesk
from app.idempotency import IdempotencyStore, InMemoryIdempotencyStore
from app.logs import log
from evals.schema import parse_triage, user_message
from gateway.pii import mask

PROMPT_VERSION = "v3"
PROMPT = (Path(__file__).parent.parent / "prompts" / f"triage.{PROMPT_VERSION}.md").read_text()
AGENT_ACTIONS = {"sent", "edited", "discarded"}


@dataclass
class Deps:
    complete: Callable[[str, str], str]  # (system, user) -> raw model text
    helpdesk: Helpdesk
    model: str = "triage-default"  # gateway alias
    kill_switch: bool = False
    shadow: bool = False
    idempotency: IdempotencyStore = field(default_factory=InMemoryIdempotencyStore)  # see app/idempotency.py
    lookup: CustomerLookup | None = None  # optional account context; see app/customer.py


def handle(ticket_id: str, text: str, d: Deps, requester_email: str | None = None) -> str:
    """Returns one of: killed, duplicate, fallback, shadow, posted."""
    t0 = time.perf_counter()

    def done(outcome: str, **fields) -> str:
        log("triage", ticket_id=ticket_id, prompt_version=PROMPT_VERSION, model=d.model, outcome=outcome,
            duration_ms=round((time.perf_counter() - t0) * 1000), **fields)  # whole request: lookup + model + note
        return outcome

    key = f"{ticket_id}:{PROMPT_VERSION}"
    if d.kill_switch:
        return done("killed")
    if not d.idempotency.claim(key):  # claim before the model call so a retried delivery in flight is a duplicate
        return done("duplicate")
    posted = False
    try:
        masked, pii_masked = mask(text)  # PII boundary: raw text never reaches the gateway
        account, lookup = None, "off"  # the requester email is used for this lookup only: never logged or sent on
        if d.lookup and requester_email:
            try:
                account = d.lookup.find(requester_email)
                lookup = "found" if account else "none"
            except Exception:  # lookup down or email not unique: draft from the ticket text alone
                lookup = "error"
        ctx = dict(pii_masked=pii_masked, account=lookup)
        user = user_message(masked, mask(account.render())[0] if account else None)
        try:
            raw = d.complete(PROMPT, user)
        except Exception as e:  # timeout or provider error
            return done("fallback", reason=type(e).__name__, **ctx)
        t = parse_triage(raw)
        if t is None:
            return done("fallback", reason="invalid_output", **ctx)
        summary = dict(category=t.category, priority=t.priority, needs_human=t.needs_human, **ctx)
        if d.shadow:  # run and log, post nothing; claim released so going live still processes it
            return done("shadow", **summary)
        note = (f"[AI draft, not sent] category={t.category} priority={t.priority} "
                f"needs_human={t.needs_human}\n\n{t.draft_reply}")
        if account:  # the sender address can be spoofed, so the agent must check before using any of it
            note += ("\n\n[Account data matched from the sender's email address; verify the sender before "
                     f"using it in a reply] {account.render()}")
        try:
            d.helpdesk.post_private_note(ticket_id, note)
        except Exception as e:
            return done("fallback", reason=f"helpdesk_{type(e).__name__}", **ctx)
        posted = True
        return done("posted", **summary)
    finally:
        if not posted:  # any non-posted outcome (even an unexpected error) frees the claim for a retry
            d.idempotency.release(key)


def record_action(ticket_id: str, action: str) -> bool:
    """What the agent did with the draft; logged so edit and discard rates can be measured."""
    if action not in AGENT_ACTIONS:
        return False
    log("agent_action", ticket_id=ticket_id, prompt_version=PROMPT_VERSION, action=action)
    return True
