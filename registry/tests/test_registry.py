import shutil
from pathlib import Path

import httpx
import pytest
import yaml

from registry.issue_keys import issue, key_request, load_tools
from registry.registry_check import ROOT, check, derive_tier

GOOD = {
    "name": "demo-tool", "owner": "demo@example.com", "description": "A demo tool for the tests.",
    "data": "internal", "human_check": "required", "tier": 2, "runbook": "rb.md",
    "allowed_models": ["triage-default"], "budget_usd_month": 10,
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A tiny repo with one valid tool; each test breaks one thing."""
    (tmp_path / "gateway").mkdir()
    shutil.copy(ROOT / "gateway/litellm.config.yaml", tmp_path / "gateway")
    (tmp_path / "CODEOWNERS").write_text("/registry/tier1/ @a\n/registry/tier2/ @a\n/registry/tier3/ @a\n")
    (tmp_path / "rb.md").write_text("runbook")
    put(tmp_path, GOOD)
    return tmp_path


def put(root: Path, tool: dict, tier_dir: str = "tier2", filename: str | None = None) -> None:
    d = root / "registry" / tier_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{filename or tool.get('name', 'x')}.yaml").write_text(yaml.safe_dump(tool))


def test_the_real_registry_passes():
    assert check(ROOT) == []


def test_good_tool_passes(repo):
    assert check(repo) == []


def test_tier_is_derived_from_data_and_human_check():
    assert derive_tier("public", "required") == 1
    assert derive_tier("public", "none") == 2
    assert derive_tier("internal", "sampled") == 2
    assert derive_tier("personal", "required") == 3
    assert derive_tier("financial", "none") == 3


@pytest.mark.parametrize("change, tier_dir, expect", [
    ({"owner": None}, "tier2", "None is not of type 'string'"),
    ({"tier": 1}, "tier2", "gives tier 2"),
    ({"data": "personal", "tier": 3}, "tier2", "move it"),
    ({"runbook": "missing.md"}, "tier2", "does not exist"),
    ({"allowed_models": ["gpt-9000"]}, "tier2", "not defined in gateway"),
    ({"name": "other-name"}, "tier2", "must equal the file name"),
    ({"surprise": 1}, "tier2", "Additional properties"),
    ({"budget_usd_month": 0}, "tier2", "minimum"),
])
def test_each_bad_case_is_rejected(repo, change, tier_dir, expect):
    shutil.rmtree(repo / "registry")
    tool = {**GOOD, **change}
    put(repo, tool, tier_dir, filename="demo-tool")
    assert any(expect in e for e in check(repo)), check(repo)


def test_missing_required_field_is_rejected(repo):
    tool = {k: v for k, v in GOOD.items() if k != "owner"}
    put(repo, tool, filename="demo-tool")
    assert any("'owner' is a required property" in e for e in check(repo))


def test_duplicate_name_is_rejected(repo):
    put(repo, GOOD, "tier2", filename="demo-tool-copy")
    assert any("already used" in e or "must equal the file name" in e for e in check(repo))


def test_missing_codeowners_rule_is_rejected(repo):
    (repo / "CODEOWNERS").write_text("/registry/tier1/ @a\n")
    assert any("CODEOWNERS" in e for e in check(repo))


def test_key_request_carries_budget_and_allow_list():
    body = key_request(GOOD)
    assert body["key_alias"] == "demo-tool" and body["models"] == ["triage-default"]
    assert body["max_budget"] == 10 and body["metadata"]["tier"] == 2


def test_issue_posts_to_the_gateway_with_the_master_key():
    def respond(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/key/generate" and req.headers["authorization"] == "Bearer master"
        return httpx.Response(200, json={"key": "sk-new"})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    assert issue(GOOD, "http://gw", "master", client) == "sk-new"


def test_every_real_tool_gets_a_key_request():
    assert {key_request(t)["key_alias"] for t in load_tools()} >= {"support-triage", "hr-jd-drafts", "finance-anomaly"}
