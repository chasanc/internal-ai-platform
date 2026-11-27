"""Real model calls are switched off for every test. Real runs happen only through `make eval` / `make smoke-real`."""
import pytest


@pytest.fixture(autouse=True)
def _insecure_local_for_tests(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL", "1")  # services refuse to start without WEBHOOK_SECRET otherwise


@pytest.fixture(autouse=True)
def _no_real_model_calls(monkeypatch):
    from evals import models

    def blocked(self, ticket):
        raise RuntimeError("real model call blocked in tests; use a fake: model or a stub")

    monkeypatch.setattr(models.LiteLLMModel, "predict", blocked)
