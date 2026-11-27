"""Quality, outage and cost report from the support-triage logs. Stdlib only; reads files, calls nothing.

    docker compose logs --no-log-prefix support-triage > triage.log
    python scripts/telemetry_report.py triage.log [--since-minutes 60] [--spend spend.json]

Exit code 1 means an alert fired (fallback rate, or the kill switch was used), so cron or CI can act on it.

--spend is a JSON list of spend rows: {"key_alias": "<tool key>", "model_group": "<gateway alias>", "spend": 0.01}.
shortcut: that row shape is assumed from the gateway's spend records, not checked against a live one; adapt the
field names in cost() if they differ.
"""
import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from evals.stats import percentile  # noqa: E402

FALLBACK_ALERT = 0.05  # same threshold as the runbook
MIN_TICKETS = 20  # below this a rate is noise, so no alert


def load(lines, now: float, since_s: float | None) -> list[dict]:
    """JSON lines only; the container's plain-text lines and anything malformed are skipped."""
    events = []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and "event" in e and (since_s is None or e.get("ts", 0) >= now - since_s):
            events.append(e)
    return events


def quality(events: list[dict]) -> dict:
    """Per prompt version: agent action rates and how many posted drafts got any action at all."""
    posted = Counter(e["prompt_version"] for e in events if e["event"] == "triage" and e["outcome"] == "posted")
    acts: dict[str, Counter] = defaultdict(Counter)
    for e in events:
        if e["event"] == "agent_action":
            acts[e["prompt_version"]][e["action"]] += 1
    out = {}
    for v in sorted(set(posted) | set(acts)):
        n = sum(acts[v].values())
        out[v] = {"posted": posted[v], "actions": n, "coverage": round(n / posted[v], 3) if posted[v] else None,
                  **{a: round(acts[v][a] / n, 3) if n else None for a in ("sent", "edited", "discarded")}}
    return out


def outage(events: list[dict]) -> dict:
    t = [e for e in events if e["event"] == "triage"]
    outcomes = Counter(e["outcome"] for e in t)
    handled = outcomes["posted"] + outcomes["shadow"] + outcomes["fallback"]  # killed and duplicates are not attempts
    ms = [e["duration_ms"] for e in t if "duration_ms" in e and e["outcome"] in {"posted", "shadow", "fallback"}]
    rate = outcomes["fallback"] / handled if handled else None
    alerts = []
    if rate is not None and handled >= MIN_TICKETS and rate > FALLBACK_ALERT:
        alerts.append(f"fallback rate {rate:.1%} over {handled} tickets (threshold {FALLBACK_ALERT:.0%})")
    if outcomes["killed"]:
        alerts.append(f"kill switch was used on {outcomes['killed']} tickets")
    return {"outcomes": dict(outcomes), "fallback_rate": None if rate is None else round(rate, 3),
            "fallback_reasons": dict(Counter(e.get("reason") for e in t if e["outcome"] == "fallback")),
            "account_lookup": dict(Counter(e["account"] for e in t if "account" in e)),
            "latency_ms": {"p50": percentile(ms, 0.5), "p95": percentile(ms, 0.95)}, "alerts": alerts}


def cost(rows: list[dict]) -> dict:
    """USD per tool key, with spend on a fallback alias shown separately: it rising is an outage signal."""
    tools: dict[str, dict] = defaultdict(lambda: {"total": 0.0, "on_fallback_alias": 0.0})
    for r in rows:
        t = tools[r.get("key_alias") or "unknown"]
        t["total"] += r["spend"]
        if "fallback" in (r.get("model_group") or ""):
            t["on_fallback_alias"] += r["spend"]
    return {k: {a: round(b, 6) for a, b in v.items()} for k, v in sorted(tools.items())}


def build(events: list[dict], spend: list[dict] | None = None) -> dict:
    report = {"quality": quality(events), "outage": outage(events)}
    if spend is not None:
        report["cost_usd"] = cost(spend)
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log", type=Path)
    ap.add_argument("--since-minutes", type=float)
    ap.add_argument("--spend", type=Path)
    a = ap.parse_args()
    since = a.since_minutes * 60 if a.since_minutes else None
    events = load(a.log.read_text().splitlines(), time.time(), since)
    report = build(events, json.loads(a.spend.read_text()) if a.spend else None)
    print(json.dumps(report, indent=1))
    for alert in report["outage"]["alerts"]:
        print("ALERT:", alert, file=sys.stderr)
    return 1 if report["outage"]["alerts"] else 0


if __name__ == "__main__":
    sys.exit(main())
