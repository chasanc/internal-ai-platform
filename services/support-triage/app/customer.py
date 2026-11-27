"""Customer context for a ticket: plan, order status and last invoice, nothing else.

The lookup key is the requester's email. It stays inside the service: never logged, never sent to the model.
The allow-list is enforced twice: the SQL reads one database view that exposes only these columns, and Account has
only these fields, so a wider view cannot leak more.
"""
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class Account:
    plan: str
    order_status: str
    invoice_number: str
    invoice_date: str
    invoice_amount: str
    invoice_status: str

    def render(self) -> str:
        """One line for the prompt. Angle brackets are dropped so a value cannot close the <account> tag."""
        v = {k: str(x).replace("<", "").replace(">", "") for k, x in vars(self).items()}
        return (f"plan={v['plan']}; order_status={v['order_status']}; last_invoice={v['invoice_number']} "
                f"{v['invoice_date']} {v['invoice_amount']} {v['invoice_status']}")


class CustomerLookup(Protocol):
    def find(self, email: str) -> Account | None:
        """None when there is no customer. Raises when the lookup fails or the email is not unique."""
        ...


def normalise(email: str) -> str:
    return email.strip().lower()


class InMemoryCustomerLookup:
    """Fake for tests and local runs."""

    def __init__(self, accounts: dict[str, Account] | None = None):
        self.accounts = {normalise(k): v for k, v in (accounts or {}).items()}

    def find(self, email: str) -> Account | None:
        return self.accounts.get(normalise(email))


# The database owner defines this view (lower-cased email, only these columns) and grants a read-only role on it.
QUERY = ("SELECT plan, order_status, invoice_number, invoice_date, invoice_amount, invoice_status "
         "FROM support_customer_context WHERE email = %s LIMIT 2")


class PostgresCustomerLookup:
    """Read-only lookup. One short-lived connection per call; `connect` is injectable so tests need no database.

    shortcut: no pooling, so every ticket pays a connection; add a pool when ticket volume makes that matter.
    """

    def __init__(self, dsn: str = "", connect: Callable | None = None):
        if connect is None:
            import psycopg  # optional dependency: pip install "psycopg[binary]"
            connect = lambda: psycopg.connect(dsn, connect_timeout=5, options="-c default_transaction_read_only=on")  # noqa: E731
        self.connect = connect

    def find(self, email: str) -> Account | None:
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(QUERY, (normalise(email),))  # parameterised: the email is never part of the SQL text
                rows = cur.fetchall()
        finally:
            conn.close()
        if len(rows) > 1:
            raise LookupError("email is not unique in the customer view")
        return Account(*(str(c) for c in rows[0])) if rows else None
