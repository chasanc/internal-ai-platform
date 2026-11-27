"""Model backends for the eval runner: a deterministic fake and a LiteLLM-backed real model."""
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from evals.schema import CATEGORIES, PRIORITIES, user_message

PROMPT_PATH = Path(__file__).parent.parent / "services/support-triage/prompts/triage.v3.md"


@dataclass
class Result:
    raw: str
    latency_s: float
    cost_usd: float = 0.0
    error: str | None = None  # set when the call itself failed; raw is then empty


class SpendCapExceeded(RuntimeError):
    pass


def _u(seed: str, tid: str, salt: str) -> float:
    """Deterministic uniform [0,1) per (seed, ticket, salt): reruns are identical."""
    h = hashlib.sha256(f"{seed}|{tid}|{salt}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


class FakeModel:
    """Right with probability `accuracy`, emits broken JSON with `invalid_rate`. Needs no keys."""

    def __init__(self, accuracy: float, invalid_rate: float = 0.0, seed: str = "0"):
        self.name = f"fake:{accuracy}:{invalid_rate}:{seed}"
        self.accuracy, self.invalid_rate, self.seed = accuracy, invalid_rate, seed

    def predict(self, ticket: dict) -> Result:
        tid = ticket["id"]
        if _u(self.seed, tid, "inv") < self.invalid_rate:
            return Result("Sure! Here is the category: billing", 0.01)
        cat = ticket["category"]
        if _u(self.seed, tid, "cat") >= self.accuracy:
            wrong = [c for c in CATEGORIES if c != cat]
            cat = wrong[int(_u(self.seed, tid, "pick") * len(wrong))]
        pri = ticket["priority"]
        if _u(self.seed, tid, "pri") >= self.accuracy:
            pri = PRIORITIES[(PRIORITIES.index(pri) + 1) % len(PRIORITIES)]
        nh = ticket["needs_human"]
        if _u(self.seed, tid, "nh") >= self.accuracy:
            nh = not nh
        body = {"category": cat, "priority": pri, "needs_human": nh, "draft_reply": "Thanks for reaching out."}
        return Result(json.dumps(body), 0.05 + _u(self.seed, tid, "lat") * 0.1)


class LiteLLMModel:
    """Any provider LiteLLM supports, e.g. 'anthropic/<model>' or 'openai/<model>'."""

    def __init__(self, model: str, timeout_s: float = 30.0, max_spend_usd: float = 1.0):
        self.name, self.timeout_s, self.max_spend_usd = model, timeout_s, max_spend_usd
        self.spent = 0.0
        self.system = PROMPT_PATH.read_text()

    def predict(self, ticket: dict) -> Result:
        import litellm  # imported lazily so the fake path and tests need no network stack

        litellm.drop_params = True  # some models reject temperature=0; they then run at their default
        if self.spent >= self.max_spend_usd:
            raise SpendCapExceeded(f"{self.name}: ${self.spent:.4f} >= cap ${self.max_spend_usd}")
        t0 = time.perf_counter()
        try:
            r = litellm.completion(
                model=self.name,
                messages=[
                    {"role": "system", "content": self.system},
                    {"role": "user", "content": user_message(ticket["text"], ticket.get("account"))},
                ],
                temperature=0,
                max_tokens=400,
                timeout=self.timeout_s,
                num_retries=1,
            )
        except Exception as e:  # timeout/provider error = fallback path, scored as invalid
            # redact long token-like strings: provider errors can echo part of a key
            msg = re.sub(r"[A-Za-z0-9_\-]{24,}", "<redacted>", str(e))[:200]
            return Result("", time.perf_counter() - t0, error=f"{type(e).__name__}: {msg}")
        cost = litellm.completion_cost(completion_response=r) or 0.0
        self.spent += cost
        return Result(r.choices[0].message.content or "", time.perf_counter() - t0, cost)


def make_model(spec: str, max_spend_usd: float = 1.0):
    """'fake:0.9[:invalid_rate[:seed]]' or a LiteLLM model string."""
    if spec.startswith("fake:"):
        parts = spec.split(":")[1:]
        return FakeModel(float(parts[0]), float(parts[1]) if len(parts) > 1 else 0.0,
                         parts[2] if len(parts) > 2 else "0")
    return LiteLLMModel(spec, max_spend_usd=max_spend_usd)
