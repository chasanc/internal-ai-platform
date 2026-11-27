"""Field-level scoring. No prose similarity: each field is compared to its label."""
import re

from evals.schema import CATEGORIES, parse_triage
from evals.stats import percentile, wilson

FIELDS = ["category", "priority", "needs_human"]


def account_leaks(tickets: list[dict], preds: list) -> dict | None:
    """For tickets with an account line: drafts that repeat a number from it (invoice number, date, amount).
    The prompt forbids this. None when no ticket has an account line."""
    rows = [(t, p) for t, p in zip(tickets, preds) if t.get("account")]
    if not rows:
        return None
    def leaked(t, p):
        values = [w for w in re.split(r"[\s;=]+", t["account"]) if any(c.isdigit() for c in w)]
        return bool(p) and any(v in p.draft_reply for v in values)
    return {"k": sum(leaked(t, p) for t, p in rows), "n": len(rows)}


def score(tickets: list[dict], results: list) -> dict:
    n = len(tickets)
    per_ticket, preds = [], []
    for t, r in zip(tickets, results):
        p = parse_triage(r.raw)
        preds.append(p)
        row = {"id": t["id"], "valid": p is not None}
        for f in FIELDS:  # an invalid output is wrong on every field
            row[f"{f}_ok"] = p is not None and getattr(p, f) == t[f]
        per_ticket.append(row)

    def rate(key: str) -> dict:
        k = sum(r[key] for r in per_ticket)
        lo, hi = wilson(k, n)
        return {"value": k / n, "ci95": [round(lo, 3), round(hi, 3)], "k": k, "n": n}

    per_class = {}
    for c in CATEGORIES:
        tp = sum(1 for t, p in zip(tickets, preds) if p and p.category == c and t["category"] == c)
        fp = sum(1 for t, p in zip(tickets, preds) if p and p.category == c and t["category"] != c)
        fn = sum(1 for t, p in zip(tickets, preds) if t["category"] == c and not (p and p.category == c))
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
        per_class[c] = {"precision": round(pr, 3), "recall": round(rc, 3), "f1": round(f1, 3),
                        "support": tp + fn}
    leaks = account_leaks(tickets, preds)
    present = [v["f1"] for v in per_class.values() if v["support"]]  # classes absent from gold don't count
    lat = [r.latency_s for r in results]
    return {
        "n": n,
        "schema_compliance": rate("valid"),
        "category_accuracy": rate("category_ok"),
        "priority_accuracy": rate("priority_ok"),
        "needs_human_accuracy": rate("needs_human_ok"),
        "category_macro_f1": round(sum(present) / len(present), 3) if present else 0.0,
        "per_class": per_class,
        "latency_p50_s": round(percentile(lat, 0.5), 3),
        "latency_p95_s": round(percentile(lat, 0.95), 3),
        "cost_per_ticket_usd": round(sum(r.cost_usd for r in results) / n, 6),
        "per_ticket": per_ticket,
        **({"account_leaks": leaks} if leaks else {}),
    }
