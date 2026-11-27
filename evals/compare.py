"""Compare two result files on the same golden set: table plus a paired significance test.

  uv run python -m evals.compare evals/results/a.json evals/results/b.json
"""
import json
import sys

from evals.stats import mcnemar_exact

ALPHA = 0.05  # significance level, shared with the CI gate

ROWS = [("category_accuracy", "category acc"), ("priority_accuracy", "priority acc"),
        ("needs_human_accuracy", "needs_human acc"), ("schema_compliance", "schema rate")]


def paired(a: dict, b: dict, key: str = "category_ok") -> tuple[int, int, float]:
    """(only A right, only B right, exact McNemar p) per ticket."""
    pa = {r["id"]: r[key] for r in a["metrics"]["per_ticket"]}
    pb = {r["id"]: r[key] for r in b["metrics"]["per_ticket"]}
    assert pa.keys() == pb.keys(), "result files cover different tickets"
    x = sum(pa[i] and not pb[i] for i in pa)
    y = sum(pb[i] and not pa[i] for i in pa)
    return x, y, mcnemar_exact(x, y)


def report(a: dict, b: dict) -> str:
    ma, mb = a["metrics"], b["metrics"]
    out = [f"{'':18}{a['model'][:28]:>30}{b['model'][:28]:>30}"]
    for k, label in ROWS:
        fa, fb = ma[k], mb[k]
        out.append(f"{label:18}{fa['value']:>14.2f} {str(fa['ci95']):>15}{fb['value']:>14.2f} {str(fb['ci95']):>15}")
    out.append(f"{'macro-F1':18}{ma['category_macro_f1']:>30}{mb['category_macro_f1']:>30}")
    out.append(f"{'p95 latency s':18}{ma['latency_p95_s']:>30}{mb['latency_p95_s']:>30}")
    out.append(f"{'$/ticket':18}{ma['cost_per_ticket_usd']:>30}{mb['cost_per_ticket_usd']:>30}")
    x, y, p = paired(a, b)
    verdict = "no significant difference" if p >= ALPHA else ("A better" if x > y else "B better")
    out.append(f"\ncategory, paired: only-A-right={x} only-B-right={y} p={p:.3f} -> {verdict}")
    return "\n".join(out)


if __name__ == "__main__":
    fa, fb = (json.load(open(p)) for p in sys.argv[1:3])
    print(report(fa, fb))
