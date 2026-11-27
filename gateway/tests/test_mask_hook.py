import asyncio

import pytest
import yaml

from gateway import mask_hook
from gateway.mask_hook import guard
from gateway.tests.test_config import CONFIG


def run(data):
    return asyncio.run(guard.async_pre_call_hook(None, None, data, "completion"))


def test_masks_user_but_not_system():
    out = run({"messages": [
        {"role": "system", "content": "Contact help@example.com is a prompt example."},
        {"role": "user", "content": "Pay DE89 3704 0044 0532 0130 00, mail anna@example.com"},
    ]})
    assert out["messages"][0]["content"] == "Contact help@example.com is a prompt example."
    assert out["messages"][1]["content"] == "Pay [IBAN], mail [EMAIL]"


def test_masks_content_parts_and_keeps_other_keys():
    out = run({"model": "m", "messages": [{"role": "user", "content": [
        {"type": "text", "text": "card 4111 1111 1111 1111"}, {"type": "image_url", "image_url": {"url": "x"}}]}]})
    assert out["model"] == "m"
    assert out["messages"][0]["content"][0]["text"] == "card [CARD]"
    assert out["messages"][0]["content"][1]["type"] == "image_url"


def test_is_idempotent_with_service_side_masking():
    once = run({"messages": [{"role": "user", "content": "a@b.co"}]})
    assert run(once)["messages"][0]["content"] == "[EMAIL]"


def test_no_messages_passes_through():
    assert run({"input": "embedding text"}) == {"input": "embedding text"}


def test_fails_closed(monkeypatch):
    def boom(_):
        raise RuntimeError("regex blew up")
    monkeypatch.setattr(mask_hook, "mask", boom)
    with pytest.raises(ValueError, match="masking failed"):
        run({"messages": [{"role": "user", "content": "hi"}]})


def test_config_registers_the_hook():
    cfg = yaml.safe_load(CONFIG.read_text())
    assert cfg["litellm_settings"]["callbacks"] == ["mask_hook.guard"]
