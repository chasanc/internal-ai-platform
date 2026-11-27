"""Deterministic PII masker, applied before text leaves the service for the model gateway.

Masks emails, card numbers (Luhn-checked), phone numbers, street addresses (English, German, Spanish, French
patterns), and financial identifiers: IBANs (mod-97 checked), account and routing numbers after a keyword, SWIFT/BIC
codes after a keyword, US tax ids. Amounts and invoice numbers are left alone. Same input, same output; no model involved. Regexes miss things, so this is one layer, not a guarantee:
names and free-form addresses still get through.
shortcut: regex only; swap in a Presidio backend when names or more languages matter.
"""
import re

EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
PHONE = re.compile(r"(?<!\w)\+?\(?\d[\d\s().-]{5,}\d(?!\w)")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_W = r"[^\W\d_]+"  # a word of letters in any script
ADDRESS = re.compile(
    rf"\b\d{{1,5}}[a-z]?\s+(?:{_W}\s+){{1,3}}(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr|boulevard|blvd)\b"  # 12 Baker Street
    rf"|\b[^\W\d_]*(?:straße|strasse|gasse|weg|platz)\s+\d{{1,5}}[a-z]?\b"  # Hauptstraße 12
    rf"|\b(?:calle|avenida|rue|via|plaza)\s+(?:{_W}\s+){{0,3}}\d{{1,5}}[a-z]?\b",  # Calle Mayor 5, Rue de la Paix 3
    re.I,
)


# Financial identifiers. Amounts, invoice numbers and vendor names are deliberately NOT masked: the finance tool needs them.
IBAN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]{2,4}){3,8}(?![A-Za-z0-9])")
ACCOUNT = re.compile(  # "account no. 12345678", "routing: 021000021", "sort code 20-00-00": keyword, then a digit run
    r"\b(account|acct|a/c|routing|sort code|bsb)\b((?:\s+(?:number|no\.?|#))?\s*[:#]?\s*)(\d[\d -]{4,}\d)", re.I
)
SWIFT = re.compile(r"\b(swift|bic)\b(\s*(?:code)?\s*[:#]?\s*)([A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b", re.I)
SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")  # US social security / tax id


def _iban(m: re.Match) -> str:
    s = re.sub(r" ", "", m.group())
    if not 15 <= len(s) <= 34:
        return m.group()
    moved = s[4:] + s[:4]
    number = "".join(str(int(c, 36)) for c in moved)  # A=10 ... Z=35
    return "[IBAN]" if int(number) % 97 == 1 else m.group()


def _account(m: re.Match) -> str:
    return f"{m.group(1)}{m.group(2)}[ACCOUNT]" if len(re.sub(r"\D", "", m.group(3))) >= 6 else m.group()


def _swift(m: re.Match) -> str:
    return f"{m.group(1)}{m.group(2)}[BANKCODE]"


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _card(m: re.Match) -> str:
    digits = re.sub(r"\D", "", m.group())
    return "[CARD]" if 13 <= len(digits) <= 19 and _luhn(digits) else m.group()


def _phone(m: re.Match) -> str:
    s = m.group()
    digits = re.sub(r"\D", "", s)
    if DATE.fullmatch(s.strip()) or not 7 <= len(digits) <= 15:
        return s
    return "[PHONE]"


def mask(text: str) -> tuple[str, int]:
    """Returns (masked text, number of replacements)."""
    count = 0

    def run(pattern: re.Pattern, fn) -> None:
        nonlocal text, count

        def sub(m: re.Match) -> str:
            nonlocal count
            out = fn(m)
            count += out != m.group()  # a rejected candidate (bad Luhn, date) is returned unchanged
            return out

        text = pattern.sub(sub, text)

    run(IBAN, _iban)  # before card and phone, which would otherwise eat its digits
    run(ACCOUNT, _account)
    run(SWIFT, _swift)
    run(SSN, lambda m: "[TAXID]")
    run(EMAIL, lambda m: "[EMAIL]")
    run(CARD, _card)
    run(PHONE, _phone)
    run(ADDRESS, lambda m: "[ADDRESS]")
    return text, count
