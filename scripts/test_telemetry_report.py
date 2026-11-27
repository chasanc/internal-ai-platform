"""Fake log lines only: the report is checked against hand-counted numbers."""
import json

from scripts.telemetry_report import build, cost, load, main


def tri(outcome, ms=100, v="v3", reason=None, account="off", ts=1000):
    e = {"ts": ts, "event": "triage", "ticket_id": "t", "prompt_version": v, "outcome": outcome,
         "duration_ms": ms, "account": account}
    return {**e, "reason": reason} if reason else e


def act(action, v="v3", ts=1000):
    return {"ts": ts, "event": "agent_action", "ticket_id": "t", "prompt_version": v, "action": action}


def test_load_keeps_json_events_only_and_applies_the_window():
    lines = ["INFO: uvicorn started", "", "{broken", json.dumps({"no": "event"}), json.dumps(tri("posted", ts=10)),
             json.dumps(tri("posted", ts=990))]
    assert len(load(lines, now=1000, since_s=None)) == 2
    assert [e["ts"] for e in load(lines, now=1000, since_s=60)] == [990]


def test_quality_rates_and_coverage_per_version():
    events = [tri("posted")] * 4 + [tri("posted", v="v2")] + [act("sent")] * 2 + [act("edited"), act("discarded")]
    q = build(events)["quality"]
    assert q["v3"] == {"posted": 4, "actions": 4, "coverage": 1.0, "sent": 0.5, "edited": 0.25, "discarded": 0.25}
    assert q["v2"] == {"posted": 1, "actions": 0, "coverage": 0.0, "sent": None, "edited": None, "discarded": None}


def test_fallback_rate_reasons_latency_and_account_lookup():
    events = ([tri("posted", ms=100, account="found")] * 16 + [tri("shadow", ms=200)] * 2
              + [tri("fallback", ms=900, reason="TimeoutError")] * 2 + [tri("duplicate", ms=1), tri("killed", ms=1)])
    o = build(events)["outage"]
    assert o["fallback_rate"] == 0.1 and o["fallback_reasons"] == {"TimeoutError": 2}
    assert o["latency_ms"] == {"p50": 100, "p95": 900}  # duplicates and killed are not model calls
    assert o["account_lookup"] == {"found": 16, "off": 6}
    assert any("fallback rate 10.0% over 20" in a for a in o["alerts"]) and any("kill switch" in a for a in o["alerts"])


def test_small_samples_do_not_alert_on_fallback_rate():
    o = build([tri("fallback"), tri("posted")])["outage"]
    assert o["fallback_rate"] == 0.5 and o["alerts"] == []


def test_empty_log_is_fine():
    r = build([])
    assert r["quality"] == {} and r["outage"]["fallback_rate"] is None and r["outage"]["alerts"] == []


def test_cost_per_tool_with_fallback_alias_separate():
    rows = [{"key_alias": "support", "model_group": "triage-default", "spend": 0.25},
            {"key_alias": "support", "model_group": "triage-fallback", "spend": 0.5},
            {"key_alias": "marketing", "model_group": "drafts-default", "spend": 1.0},
            {"model_group": "mock", "spend": 0.0}]
    assert cost(rows) == {"marketing": {"total": 1.0, "on_fallback_alias": 0.0},
                          "support": {"total": 0.75, "on_fallback_alias": 0.5},
                          "unknown": {"total": 0.0, "on_fallback_alias": 0.0}}


def test_cli_exit_code_signals_an_alert(tmp_path, monkeypatch, capsys):
    log = tmp_path / "t.log"
    log.write_text("\n".join(json.dumps(tri("fallback", ts=4_000_000_000)) for _ in range(30)))
    monkeypatch.setattr("sys.argv", ["telemetry_report", str(log)])
    assert main() == 1
    assert "ALERT" in capsys.readouterr().err
    log.write_text(json.dumps(tri("posted")))
    assert main() == 0
