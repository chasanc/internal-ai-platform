"""CI regression gate. Exit 1 if the candidate is clearly worse than the committed baseline.

  uv run python -m evals.gate evals/results/candidate.json evals/baselines/support-triage.json

Fails on any of:
  - schema compliance below FLOORS (a model that breaks the output contract never ships)
  - category accuracy below FLOORS
  - category accuracy significantly worse than baseline (paired exact McNemar, p < 0.05)
A drop inside the noise passes: at n=50 a 4-point swing is not evidence (see docs/adr/0001).
"""
import json
import sys

from evals.compare import ALPHA, paired

FLOORS = {"schema_compliance": 0.95, "category_accuracy": 0.70}


def check(cand: dict, base: dict) -> list[str]:
    fails = []
    for k, floor in FLOORS.items():
        v = cand["metrics"][k]["value"]
        if v < floor:
            fails.append(f"{k} {v:.2f} below floor {floor}")
    base_only, cand_only, p = paired(base, cand)
    if p < ALPHA and base_only > cand_only:
        fails.append(f"category regression vs baseline: baseline-only-right={base_only} "
                     f"candidate-only-right={cand_only} p={p:.3f}")
    return fails


if __name__ == "__main__":
    cand, base = (json.load(open(p)) for p in sys.argv[1:3])
    fails = check(cand, base)
    for f in fails:
        print("FAIL:", f)
    print("gate:", "FAILED" if fails else "passed")
    sys.exit(1 if fails else 0)
