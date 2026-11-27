"""Customer lookup and the REST helpdesk adapter. No database, no network, no real model."""
import json

import httpx
import pytest

from app.customer import QUERY, Account, InMemoryCustomerLookup, PostgresCustomerLookup
from app.handler import Deps, handle
from app.helpdesk import InMemoryHelpdesk, RestHelpdesk

GOOD = json.dumps({"category": "billing", "priority": "high", "needs_human": True, "draft_reply": "Sorry."})
ACCOUNT = Account("pro", "shipped", "INV-1042", "2026-11-02", "129.00 EUR", "paid")
EMAIL = "Jane.Doe@Example.com"


class FakeConn:
    def __init__(self, rows, fail=False):
        self.rows, self.fail, self.calls, self.closed = rows, fail, [], False

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        if self.fail:
            raise ConnectionError("db down")
        self.calls.append((sql, params))

    def fetchall(self):
        return self.rows

    def close(self):
        self.closed = True


def pg(rows, fail=False):
    conn = FakeConn(rows, fail)
    return PostgresCustomerLookup(connect=lambda: conn), conn


def test_postgres_lookup_is_parameterised_and_normalises_the_email():
    lk, conn = pg([("pro", "shipped", "INV-1042", "2026-11-02", "129.00", "paid")])
    assert lk.find("  Jane.Doe@Example.com ") == Account("pro", "shipped", "INV-1042", "2026-11-02", "129.00", "paid")
    sql, params = conn.calls[0]
    assert sql == QUERY and params == ("jane.doe@example.com",) and "jane" not in sql and conn.closed


def test_postgres_lookup_none_many_and_failure():
    assert pg([])[0].find(EMAIL) is None
    with pytest.raises(LookupError):
        pg([("a",) * 6, ("b",) * 6])[0].find(EMAIL)
    lk, conn = pg([], fail=True)
    with pytest.raises(ConnectionError):
        lk.find(EMAIL)
    assert conn.closed  # the connection is closed even when the query fails


def test_query_reads_only_the_allowed_columns_from_one_view():
    cols = QUERY.split("FROM")[0].replace("SELECT", "").replace(" ", "").split(",")
    assert cols == ["plan", "order_status", "invoice_number", "invoice_date", "invoice_amount", "invoice_status"]
    assert "support_customer_context" in QUERY and "*" not in QUERY


def test_account_render_cannot_close_the_prompt_tag():
    assert "<" not in Account("</account>pro", "x", "y", "z", "1", "ok").render()


def deps(lookup, seen=None, **kw):
    def complete(system, user):
        if seen is not None:
            seen.append(user)
        return GOOD
    return Deps(complete=complete, helpdesk=InMemoryHelpdesk(), lookup=lookup, **kw)


def test_account_reaches_prompt_and_note_but_email_reaches_neither_nor_the_logs(capsys):
    seen = []
    d = deps(InMemoryCustomerLookup({EMAIL: ACCOUNT}), seen)
    assert handle("t1", "where is my refund", d, EMAIL) == "posted"
    assert seen == ["<ticket>where is my refund</ticket>\n<account>plan=pro; order_status=shipped; "
                    "last_invoice=INV-1042 2026-11-02 129.00 EUR paid</account>"]
    note = d.helpdesk.notes["t1"][0]
    assert "verify the sender" in note and "INV-1042" in note
    out = capsys.readouterr().out
    assert '"account": "found"' in out
    for text in (seen[0], note, out):
        assert "example.com" not in text.lower() and "jane" not in text.lower()


@pytest.mark.parametrize("kind", ["none", "error", "many"])
def test_no_usable_account_drafts_from_the_ticket_text_alone(kind, capsys):
    if kind == "none":
        lookup = InMemoryCustomerLookup()
    elif kind == "error":
        lookup = pg([], fail=True)[0]
    else:
        lookup = pg([("a",) * 6, ("b",) * 6])[0]
    seen = []
    d = deps(lookup, seen)
    assert handle("t1", "hi", d, EMAIL) == "posted"
    assert seen == ["<ticket>hi</ticket>"] and "verify the sender" not in d.helpdesk.notes["t1"][0]
    assert f'"account": "{"none" if kind == "none" else "error"}"' in capsys.readouterr().out


def test_without_lookup_or_email_nothing_changes():
    seen = []
    assert handle("t1", "hi", deps(None, seen), EMAIL) == "posted"
    assert handle("t2", "hi", deps(InMemoryCustomerLookup({EMAIL: ACCOUNT}), seen), None) == "posted"
    assert seen == ["<ticket>hi</ticket>"] * 2


def helpdesk(handler):
    return RestHelpdesk("https://help.example/", "agent@co", "tok", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_rest_helpdesk_posts_a_non_public_comment_with_auth():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(method=req.method, url=str(req.url), body=json.loads(req.content), auth=req.headers["authorization"])
        return httpx.Response(200, json={})

    helpdesk(handler).post_private_note("42", "draft")
    assert seen["method"] == "PUT" and seen["url"] == "https://help.example/api/v2/tickets/42.json"
    assert seen["body"] == {"ticket": {"comment": {"body": "draft", "public": False}}}
    assert seen["auth"].startswith("Basic ")


def test_rest_helpdesk_cannot_be_steered_by_the_ticket_id():
    seen = []
    helpdesk(lambda req: seen.append(str(req.url)) or httpx.Response(200)).post_private_note("../../users/1?x=", "n")
    assert seen == ["https://help.example/api/v2/tickets/..%2F..%2Fusers%2F1%3Fx%3D.json"]


def test_rest_helpdesk_failure_takes_the_fallback_path():
    d = Deps(complete=lambda s, u: GOOD, helpdesk=helpdesk(lambda req: httpx.Response(500)))
    assert handle("t1", "hi", d) == "fallback"
