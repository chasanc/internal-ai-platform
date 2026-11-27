import pytest

from evals.run import load_tickets
from gateway.pii import mask


@pytest.mark.parametrize("text, expected", [
    ("Mail me at anna.k@example.com please", "Mail me at [EMAIL] please"),
    ("Card 4111 1111 1111 1111 was charged", "Card [CARD] was charged"),
    ("Card 4111-1111-1111-1111", "Card [CARD]"),
    ("Call +49 170 1234567 tomorrow", "Call [PHONE] tomorrow"),
    ("Call (555) 123-4567", "Call [PHONE]"),
    ("Ship to 12 Baker Street today", "Ship to [ADDRESS] today"),
    ("Ich wohne in der Hauptstraße 12.", "Ich wohne in der [ADDRESS]."),
    ("Vivo en Calle Mayor 5, Madrid", "Vivo en [ADDRESS], Madrid"),
    ("J'habite Rue de la Paix 3", "J'habite [ADDRESS]"),
    ("我的邮箱是 li.wei@example.cn，电话 +86 138 0013 8000", "我的邮箱是 [EMAIL]，电话 [PHONE]"),
    ("Refund to DE89 3704 0044 0532 0130 00 please", "Refund to [IBAN] please"),
    ("IBAN GB82WEST12345698765432", "IBAN [IBAN]"),
    ("Account number: 12345678, sort code 20-00-00", "Account number: [ACCOUNT], sort code [ACCOUNT]"),
    ("routing 021000021 acct no. 000123456789", "routing [ACCOUNT] acct no. [ACCOUNT]"),
    ("SWIFT: DEUTDEFF500", "SWIFT: [BANKCODE]"),
    ("SSN 078-05-1120", "SSN [TAXID]"),
])
def test_masks(text, expected):
    assert mask(text)[0] == expected


@pytest.mark.parametrize("text", [
    "Order 88123 arrived on 2026-11-27",
    "App version 4.2.1 on Android 14",
    "Card 1234 5678 9012 3456",  # fails the Luhn check, so it is not a card
    "Tracking has said 'in transit' for 9 days",
    "INV-1003 Hosting. Vendor HostNet (known). Amount 4,980.00 EUR. Usual 5,000.",  # amounts and invoice ids stay
    "DE89 3704 0044 0532 0130 01",  # fails mod-97, so it is not an IBAN
    "Account 42 is overdue by 12345 days",  # keyword but too few digits
    "Order DE12 ABCD arrived",  # too short for an IBAN
])
def test_leaves_non_pii_alone(text):
    assert mask(text) == (text, 0)


def test_is_deterministic_and_counts():
    t = "a@b.co and a@b.co, +49 170 1234567"
    assert mask(t) == mask(t) == ("[EMAIL] and [EMAIL], [PHONE]", 3)


def test_department_golden_sets_are_unchanged():
    """Masking must not damage the inputs the department tools need (amounts, invoice ids, vendors)."""
    import json
    from pathlib import Path
    rows = [json.loads(line) for p in Path("tools").glob("*/golden.jsonl") for line in p.read_text().splitlines() if line]
    assert rows and [r["id"] for r in rows if mask(r["text"])[0] != r["text"]] == []


def test_golden_tickets_are_unchanged():
    """The synthetic evals contain no PII, so the masker must not rewrite any of them."""
    assert [(t["id"], mask(t["text"])[0]) for t in load_tickets() if mask(t["text"])[0] != t["text"]] == []
