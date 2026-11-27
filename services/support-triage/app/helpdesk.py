"""Helpdesk adapter. The service only ever writes a private note; it never replies to the customer."""
from typing import Protocol
from urllib.parse import quote

import httpx


class Helpdesk(Protocol):
    def post_private_note(self, ticket_id: str, body: str) -> None: ...


class InMemoryHelpdesk:
    """Generic fake used in tests and local runs."""

    def __init__(self):
        self.notes: dict[str, list[str]] = {}

    def post_private_note(self, ticket_id: str, body: str) -> None:
        self.notes.setdefault(ticket_id, []).append(body)


class RestHelpdesk:
    """Adds a non-public comment through a REST API shaped like the common ticket-comment endpoint:
    PUT {base}/api/v2/tickets/{id}.json with {"ticket": {"comment": {"body": ..., "public": false}}}, basic auth
    "<user>/token" + API token. For a platform with a different API, replace this class; nothing else changes.

    shortcut: not checked against a live helpdesk, and no retry; a failure takes the single fallback path.
    """

    def __init__(self, base_url: str, user: str, token: str, timeout_s: float = 10.0,
                 client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.auth = (f"{user}/token", token)
        self.timeout_s = timeout_s
        self.client = client or httpx.Client()

    def post_private_note(self, ticket_id: str, body: str) -> None:
        r = self.client.put(
            f"{self.base_url}/api/v2/tickets/{quote(ticket_id, safe='')}.json",  # the id comes from a webhook body
            json={"ticket": {"comment": {"body": body, "public": False}}},
            auth=self.auth, timeout=self.timeout_s,
        )
        r.raise_for_status()
