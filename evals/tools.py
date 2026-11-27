"""Generic field-level eval for the small department tools in tools/<name>/.

Each tool dir holds prompt.md, contract.json (allowed enum values + free-text fields) and golden.jsonl.
`complete(system, user) -> str` is injected, so tests and CI use a stub; a real model is wired in by the caller.
Invalid output (not JSON, wrong enum, missing or extra field) counts as wrong, as in the triage evals.
"""
import json
from pathlib import Path

from evals.stats import wilson

TOOLS = Path(__file__).parent.parent / "tools"


def load(name: str, root: Path = TOOLS) -> tuple[str, dict, list[dict]]:
    d = root / name
    golden = [json.loads(line) for line in (d / "golden.jsonl").read_text().splitlines() if line.strip()]
    return (d / "prompt.md").read_text(), json.loads((d / "contract.json").read_text()), golden


def parse(raw: str, contract: dict) -> dict | None:
    """Return the structured fields if raw obeys the contract, else None."""
    try:
        out = json.loads(raw)
    except ValueError:
        return None
    fields, text = contract["fields"], contract["text"]
    if not isinstance(out, dict) or set(out) != set(fields) | set(text):
        return None
    for key, allowed in fields.items():
        ok = isinstance(out[key], bool) if allowed == "bool" else out[key] in allowed
        if not ok:
            return None
    if not all(isinstance(out[k], str) and out[k] for k in text):
        return None
    return {k: out[k] for k in fields}


def run(name: str, complete, root: Path = TOOLS) -> dict:
    prompt, contract, golden = load(name, root)
    valid = 0
    right = {k: 0 for k in contract["fields"]}
    for item in golden:
        got = parse(complete(prompt, f"<input>{item['text']}</input>"), contract)
        valid += got is not None
        for k in right:
            right[k] += got is not None and got[k] == item["expected"][k]
    n = len(golden)
    return {"tool": name, "n": n, "valid": valid / n,
            "fields": {k: {"acc": v / n, "ci95": wilson(v, n)} for k, v in right.items()}}


def main(argv: list[str] | None = None) -> int:
    """Real-model run for one tool: uv run python -m evals.tools <tool> <litellm model> [--max-spend 0.10] [--out f.json]"""
    import argparse
    import re

    import litellm  # lazy: tests never need the network stack

    ap = argparse.ArgumentParser()
    ap.add_argument("tool")
    ap.add_argument("model")
    ap.add_argument("--max-spend", type=float, default=0.10)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    litellm.drop_params = True
    spent, replies = 0.0, {}

    def complete(system: str, user: str) -> str:
        nonlocal spent
        if spent >= a.max_spend:
            raise SystemExit(f"spend cap ${a.max_spend} reached")
        try:
            r = litellm.completion(model=a.model, temperature=0, max_tokens=400, timeout=30, num_retries=1,
                                   messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        except Exception as e:  # scored as invalid, as in the triage evals
            print("call failed:", type(e).__name__, re.sub(r"[A-Za-z0-9_\-]{24,}", "<redacted>", str(e))[:120])
            return ""
        spent += litellm.completion_cost(completion_response=r) or 0.0
        replies[user] = r.choices[0].message.content or ""
        return replies[user]

    res = run(a.tool, complete) | {"model": a.model, "cost_usd": round(spent, 6)}
    _, contract, golden = load(a.tool)
    res["misses"] = [g["id"] for g in golden
                     if (got := parse(replies.get(f"<input>{g['text']}</input>", ""), contract)) is None
                     or any(got[k] != g["expected"][k] for k in contract["fields"])]
    print(json.dumps({k: res[k] for k in ("tool", "model", "n", "valid", "cost_usd", "misses")} |
                     {k: round(v["acc"], 3) for k, v in res["fields"].items()}))
    if a.out:
        a.out.write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
