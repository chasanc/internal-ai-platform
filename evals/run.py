"""Run one model over the golden set and write a result file.

  uv run python -m evals.run fake:0.9 --out evals/results/fake.json
  uv run python -m evals.run anthropic/<model> --max-spend 0.50 --out evals/results/a.json
"""
import argparse
import json
from pathlib import Path

from evals.models import PROMPT_PATH, make_model
from evals.score import score

DATASET = Path(__file__).parent / "datasets/support-triage.golden.jsonl"


def load_tickets(path: Path = DATASET) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run(spec: str, max_spend: float = 1.0, dataset: Path = DATASET) -> dict:
    tickets = load_tickets(dataset)
    model = make_model(spec, max_spend)
    results = [model.predict(t) for t in tickets]
    errors = [r.error for r in results if r.error]
    if errors:
        print(f"{len(errors)}/{len(results)} calls failed, first: {errors[0]}")
    return {
        "model": spec,
        "dataset": dataset.name,
        "prompt": PROMPT_PATH.name,
        "metrics": score(tickets, results),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-spend", type=float, default=1.0, help="hard USD cap for this run")
    ap.add_argument("--dataset", type=Path, default=DATASET)
    a = ap.parse_args()
    res = run(a.model, a.max_spend, a.dataset)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1))
    m = res["metrics"]
    print(f"{a.model}: category {m['category_accuracy']['value']:.2f} "
          f"schema {m['schema_compliance']['value']:.2f} p95 {m['latency_p95_s']}s "
          f"${m['cost_per_ticket_usd']}/ticket")


if __name__ == "__main__":
    main()
