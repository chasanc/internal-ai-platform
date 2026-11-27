import pytest

from evals.models import make_model


def test_tests_cannot_make_real_model_calls():
    with pytest.raises(RuntimeError, match="blocked in tests"):
        make_model("anthropic/claude-haiku-5-5").predict({"id": "t1", "text": "hi"})


def test_fake_models_still_work():
    assert make_model("fake:1.0").predict({"id": "t1", "text": "hi", "category": "other", "priority": "low",
                                          "needs_human": False}).raw.startswith("{")
