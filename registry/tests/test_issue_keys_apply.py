import stat

import httpx
import pytest

from registry import issue_keys
from registry.issue_keys import existing_aliases, load_tools, main


@pytest.fixture
def gateway(monkeypatch):
    """Fake gateway: remembers issued keys; `have` is the set of aliases that already have one."""
    monkeypatch.setenv("LITELLM_URL", "http://gw")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "master")
    state = {"have": set(), "issued": []}
    monkeypatch.setattr(issue_keys, "existing_aliases", lambda url, key, client=None: state["have"])

    def fake_issue(tool, url, key, client=None):
        state["issued"].append(tool["name"])
        return f"sk-{tool['name']}"

    monkeypatch.setattr(issue_keys, "issue", fake_issue)
    return state


def test_apply_without_out_is_refused_and_issues_nothing(gateway, capsys):
    assert main(["--apply"]) == 2
    assert gateway["issued"] == [] and "--out" in capsys.readouterr().err


def test_apply_saves_every_key_owner_only(gateway, tmp_path):
    out = tmp_path / "keys.txt"
    assert main(["--apply", "--out", str(out)]) == 0
    assert dict(line.split("=", 1) for line in out.read_text().splitlines()) == {t["name"]: f"sk-{t['name']}" for t in load_tools()}
    assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_existing_aliases_are_skipped(gateway, tmp_path, capsys):
    gateway["have"] = {"support-triage"}
    out = tmp_path / "keys.txt"
    main(["--apply", "--out", str(out)])
    assert "support-triage" not in gateway["issued"] and "support-triage=" not in out.read_text()
    assert "skipped support-triage" in capsys.readouterr().out


def test_nothing_to_do_writes_no_file(gateway, tmp_path):
    gateway["have"] = {t["name"] for t in load_tools()}
    out = tmp_path / "keys.txt"
    assert main(["--apply", "--out", str(out)]) == 0 and not out.exists()


def test_an_existing_file_is_never_overwritten(gateway, tmp_path):
    out = tmp_path / "keys.txt"
    out.write_text("precious")
    with pytest.raises(FileExistsError):
        main(["--apply", "--out", str(out)])
    assert out.read_text() == "precious" and gateway["issued"] == []


def test_existing_aliases_reads_every_page():
    def handler(req):
        page = int(req.url.params["page"])
        return httpx.Response(200, json={"keys": [{"key_alias": f"t{page}"}, {"key_alias": None}, "sk-hash"], "total_pages": 2})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert existing_aliases("http://gw", "master", client) == {"t1", "t2"}
