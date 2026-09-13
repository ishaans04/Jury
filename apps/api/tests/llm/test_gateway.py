import pytest

from jury.llm.gateway import BudgetExceeded, LiveLLMClient
from jury.llm.models import DEFAULT_MODEL_IDS, FALLBACK_CHAIN, resolve_model
from jury.settings import Settings


def test_model_ids_live_in_exactly_one_map():
    """PRD §15.1: keep them in a single config map, not hardcoded across the code."""
    assert set(DEFAULT_MODEL_IDS) == {"reasoning", "fast", "fallback"}


def test_env_overrides_the_default_model_id():
    s = Settings(_env_file=None, LLM_MODEL_FAST="groq/llama-custom-8b")
    assert resolve_model("fast", s) == "groq/llama-custom-8b"


def test_missing_env_falls_back_to_the_documented_default(monkeypatch):
    monkeypatch.delenv("LLM_MODEL_REASONING", raising=False)
    s = Settings(_env_file=None)
    assert resolve_model("reasoning", s) == DEFAULT_MODEL_IDS["reasoning"]


def test_reasoning_degrades_to_fast_then_fallback():
    """PRD §15.2: if the 70B tier throttles, fall back within Groq rather than
    failing the run."""
    assert FALLBACK_CHAIN["reasoning"] == ("reasoning", "fast", "fallback")
    assert FALLBACK_CHAIN["fast"] == ("fast", "fallback")


async def test_a_429_on_the_first_model_tries_the_next(monkeypatch):
    calls: list[str] = []

    async def fake_acompletion(*, model, messages, **kw):
        calls.append(model)
        if len(calls) == 1:
            raise RuntimeError("429 rate_limit_exceeded")
        return {"choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2}}

    monkeypatch.setattr("jury.llm.gateway.acompletion", fake_acompletion)
    client = LiveLLMClient(Settings(_env_file=None, GROQ_API_KEY="sk-x"))
    r = await client.complete(model="reasoning", messages=[{"role": "user", "content": "x"}])
    assert r.text == "ok"
    assert len(calls) == 2 and calls[0] != calls[1]


async def test_exhausting_the_chain_raises_rather_than_inventing_an_answer(monkeypatch):
    async def always_429(**kw):
        raise RuntimeError("429 rate_limit_exceeded")
    monkeypatch.setattr("jury.llm.gateway.acompletion", always_429)
    client = LiveLLMClient(Settings(_env_file=None, GROQ_API_KEY="sk-x"))
    with pytest.raises(RuntimeError):
        await client.complete(model="fast", messages=[{"role": "user", "content": "x"}])


async def test_budget_cap_stops_the_run(monkeypatch):
    """PRD §17.2: ~120 LLM calls per run, enforced not advisory."""
    async def ok(**kw):
        return {"choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    monkeypatch.setattr("jury.llm.gateway.acompletion", ok)
    client = LiveLLMClient(Settings(_env_file=None, GROQ_API_KEY="sk-x"), max_calls=2)
    for _ in range(2):
        await client.complete(model="fast", messages=[{"role": "user", "content": "x"}])
    with pytest.raises(BudgetExceeded):
        await client.complete(model="fast", messages=[{"role": "user", "content": "x"}])


async def test_json_mode_is_requested_when_asked(monkeypatch):
    seen: dict = {}

    async def capture(**kw):
        seen.update(kw)
        return {"choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    monkeypatch.setattr("jury.llm.gateway.acompletion", capture)
    client = LiveLLMClient(Settings(_env_file=None, GROQ_API_KEY="sk-x"))
    await client.complete(model="fast", messages=[{"role": "user", "content": "x"}],
                          json_mode=True)
    assert seen["response_format"] == {"type": "json_object"}


async def test_temperature_defaults_to_zero_for_reproducibility(monkeypatch):
    seen: dict = {}

    async def capture(**kw):
        seen.update(kw)
        return {"choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    monkeypatch.setattr("jury.llm.gateway.acompletion", capture)
    client = LiveLLMClient(Settings(_env_file=None, GROQ_API_KEY="sk-x"))
    await client.complete(model="fast", messages=[{"role": "user", "content": "x"}])
    assert seen["temperature"] == 0.0
