"""Output contract shared by the triage service and the evals."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

CATEGORIES = ["billing", "shipping", "returns", "technical", "account", "other"]
PRIORITIES = ["low", "normal", "high", "urgent"]


class Triage(BaseModel):
    # unknown fields = invalid, same as a bad category; strict = "yes" or 1 is not a bool
    model_config = ConfigDict(extra="forbid", strict=True)

    category: Literal["billing", "shipping", "returns", "technical", "account", "other"]
    priority: Literal["low", "normal", "high", "urgent"]
    needs_human: bool
    draft_reply: str = ""


_TAGS = re.compile(r"</?\s*(ticket|account)\b[^>]*>", re.I)


def user_message(text: str, account: str | None = None) -> str:
    """The user turn. The service and the evals both build it here, so they cannot drift apart.
    Ticket text cannot close or forge a tag: ticket and account tags inside it are removed."""
    msg = f"<ticket>{_TAGS.sub('', text)}</ticket>"
    return f"{msg}\n<account>{account}</account>" if account else msg


def parse_triage(raw: str) -> Triage | None:
    """Strict: anything but one valid JSON object is None (= fallback). Service and evals share this."""
    try:
        return Triage.model_validate_json(raw)
    except ValueError:
        return None
