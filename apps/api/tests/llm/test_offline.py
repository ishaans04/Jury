import pytest

from jury.settings import Settings
from jury.transport.factory import build_transports


@pytest.fixture()
def empty_env(monkeypatch):
    for k in ("GROQ_API_KEY", "BRAVE_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY",
              "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN", "JURY_OFFLINE"):
        monkeypatch.delenv(k, raising=False)
    return Settings(_env_file=None)


def test_no_keys_selects_fixture_transports(empty_env):
    """Spec §3: the build must be verifiable before any credential exists."""
    t = build_transports(empty_env)
    assert t.offline is True
    assert type(t.llm).__name__ == "FixtureLLMClient"
    assert type(t.search).__name__ == "FixtureSearchClient"
    assert type(t.fetch).__name__ == "FixtureFetchClient"


def test_kv_falls_back_to_memory_without_upstash(empty_env):
    t = build_transports(empty_env)
    assert type(t.kv).__name__ == "MemoryKV"


async def test_fixture_llm_returns_recorded_text(empty_env):
    t = build_transports(empty_env)
    r = await t.llm.complete(model="fast",
                             messages=[{"role": "user", "content": "archetype: dog walking app"}],
                             json_mode=True)
    assert r.text
    assert r.prompt_tokens >= 0


async def test_fixture_llm_is_deterministic_for_the_same_prompt(empty_env):
    t = build_transports(empty_env)
    msgs = [{"role": "user", "content": "same prompt"}]
    a = await t.llm.complete(model="fast", messages=msgs)
    b = await t.llm.complete(model="fast", messages=msgs)
    assert a.text == b.text


async def test_fixture_fetch_never_hits_the_network(empty_env, monkeypatch):
    def explode(*a, **k):
        raise AssertionError("offline transport attempted a real network call")
    monkeypatch.setattr("httpx.AsyncClient.request", explode)
    t = build_transports(empty_env)
    r = await t.fetch.fetch("https://example.test/pricing")
    assert r.status == 200 and r.text


async def test_memory_kv_token_bucket_enforces_the_limit(empty_env):
    t = build_transports(empty_env)
    allowed = [await t.kv.incr_bucket("brave", limit=3, window_s=60) for _ in range(5)]
    assert allowed == [True, True, True, False, False]


def test_explicit_offline_flag_overrides_present_keys(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "sk-real")
    monkeypatch.setenv("JURY_OFFLINE", "1")
    t = build_transports(Settings(_env_file=None))
    assert t.offline is True


def test_a_real_key_with_offline_zero_selects_live_transports(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "sk-real")
    monkeypatch.setenv("JURY_OFFLINE", "0")
    t = build_transports(Settings(_env_file=None))
    assert t.offline is False
    assert type(t.llm).__name__ == "LiveLLMClient"
