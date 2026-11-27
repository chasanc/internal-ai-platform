import re
from pathlib import Path

import yaml

CONFIG = Path(__file__).parent.parent / "litellm.config.yaml"


def test_config_is_safe():
    text = CONFIG.read_text()
    cfg = yaml.safe_load(text)
    assert cfg["litellm_settings"]["turn_off_message_logging"] is True  # no bodies in logs
    assert not re.search(r"sk-[A-Za-z0-9]{10,}", text)  # no literal keys
    for m in cfg["model_list"]:
        p = m["litellm_params"]
        if not m["model_name"].startswith("mock"):
            assert p["api_key"].startswith("os.environ/"), m["model_name"]
            assert p["timeout"] <= 60, m["model_name"]
    assert cfg["router_settings"]["num_retries"] == 1


def test_fallbacks_point_at_defined_aliases():
    cfg = yaml.safe_load(CONFIG.read_text())
    aliases = {m["model_name"] for m in cfg["model_list"]}
    for rule in cfg["router_settings"]["fallbacks"]:
        for src, dsts in rule.items():
            assert {src, *dsts} <= aliases
