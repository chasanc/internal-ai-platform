import json
import re
from pathlib import Path

import pytest

from evals import tools

NAMES = sorted(p.name for p in tools.TOOLS.iterdir() if p.is_dir())
BANNED = re.compile(r"refurbed|helix|reos|thanos|zendesk|similarweb|zapier", re.I)


def oracle(name):
    """Stub model that reads the answer from the golden set: proves the pipeline, says nothing about quality."""
    _, contract, golden = tools.load(name)
    by_text = {f"<input>{g['text']}</input>": g for g in golden}

    def complete(system, user):
        body = dict(by_text[user]["expected"]) | {k: "ok" for k in contract["text"]}
        return json.dumps(body)

    return complete


def test_all_tools_present():
    assert NAMES == ["competitor-digest", "finance-anomaly", "hr-jd-drafts", "marketing-campaign-brief",
                     "pr-risk-summary", "supplier-delay-triage"]


@pytest.mark.parametrize("name", NAMES)
def test_golden_set_is_well_formed(name):
    _, contract, golden = tools.load(name)
    assert len(golden) >= 16 and len({g["id"] for g in golden}) == len(golden)
    assert any("injection" in g["tags"] for g in golden)
    for g in golden:
        assert set(g["expected"]) == set(contract["fields"])
        for k, allowed in contract["fields"].items():
            assert isinstance(g["expected"][k], bool) if allowed == "bool" else g["expected"][k] in allowed


@pytest.mark.parametrize("name", NAMES)
def test_oracle_scores_perfect(name):
    r = tools.run(name, oracle(name))
    assert r["valid"] == 1.0 and all(f["acc"] == 1.0 for f in r["fields"].values())


@pytest.mark.parametrize("raw", ["not json", "[]", '{"x": 1}', json.dumps({"cause": "rain", "severity": "low", "reply": "a"}),
                                 json.dumps({"cause": "weather", "severity": "low", "reply": "a", "extra": 1}),
                                 json.dumps({"cause": "weather", "severity": "low", "reply": ""})])
def test_invalid_output_counts_as_wrong(raw):
    r = tools.run("supplier-delay-triage", lambda s, u: raw)
    assert r["valid"] == 0.0 and all(f["acc"] == 0.0 for f in r["fields"].values())


@pytest.mark.parametrize("name", NAMES)
def test_no_company_terms(name):
    for f in (tools.TOOLS / name).iterdir():
        assert not BANNED.search(f.read_text()), f
