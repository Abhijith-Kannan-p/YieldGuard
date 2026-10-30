import pytest

from app import llm


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm.config, "LLM_MODEL", "gemini-main")
    monkeypatch.setattr(llm.config, "LLM_FALLBACK_MODEL", "gemini-lite")


def script(monkeypatch, outcomes):
    calls = []

    async def fake_call(model, msg):
        calls.append(model)
        out = outcomes[model]
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(llm, "_call", fake_call)
    return calls


async def test_no_key_raises(monkeypatch):
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "")
    with pytest.raises(llm.LLMError, match="GEMINI_API_KEY"):
        await llm.generate("hi")


async def test_main_model_used_when_ok(keyed, monkeypatch):
    calls = script(monkeypatch, {"gemini-main": {"answer": "ok"}})
    assert await llm.generate("hi") == ({"answer": "ok"}, "gemini-main")
    assert calls == ["gemini-main"]


async def test_rate_limit_falls_back_to_lite_model(keyed, monkeypatch):
    calls = script(monkeypatch, {"gemini-main": llm._Retryable("rate limit reached"),
                                 "gemini-lite": {"answer": "ok"}})
    assert (await llm.generate("hi"))[1] == "gemini-lite"
    assert calls == ["gemini-main", "gemini-lite"]


async def test_both_models_down(keyed, monkeypatch):
    script(monkeypatch, {"gemini-main": llm._Retryable("HTTP 503"),
                         "gemini-lite": llm._Retryable("rate limit reached")})
    with pytest.raises(llm.LLMError, match="rate limit"):
        await llm.generate("hi")


async def test_non_retryable_error_not_retried(keyed, monkeypatch):
    calls = script(monkeypatch, {"gemini-main": llm.LLMError("language model rejected the API key")})
    with pytest.raises(llm.LLMError, match="API key"):
        await llm.generate("hi")
    assert calls == ["gemini-main"]


def test_stale_model_name_is_ignored(monkeypatch):
    import importlib
    from app import config
    monkeypatch.setenv("LLM_MODEL", "claude-opus-5-5")
    try:
        assert importlib.reload(config).LLM_MODEL.startswith("gemini")
    finally:
        monkeypatch.delenv("LLM_MODEL")
        importlib.reload(config)
