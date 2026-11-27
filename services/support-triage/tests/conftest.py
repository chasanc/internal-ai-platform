import pytest


@pytest.fixture(autouse=True)
def _local_defaults(monkeypatch):
    """Tests build apps without a secret, so they opt in to insecure local mode; the fail-closed tests opt back out."""
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("IDEMPOTENCY_DB", raising=False)
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL", "1")
