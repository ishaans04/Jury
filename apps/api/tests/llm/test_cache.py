from jury.llm.cache import CachedLLMClient, prompt_cache_key
from jury.transport.kv import MemoryKV
from jury.transport.protocols import LLMResponse


class Counting:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, *, model, messages, json_mode=False, temperature=0.0):
        self.calls += 1
        return LLMResponse(text=f"r{self.calls}", model=model,
                           prompt_tokens=1, completion_tokens=1)


async def test_identical_prompt_is_served_from_cache():
    """PRD §15.3: aggressive Redis caching keyed by prompt hash is the mitigation
    for Groq being a single point of failure."""
    inner = Counting()
    client = CachedLLMClient(inner, MemoryKV())
    msgs = [{"role": "user", "content": "hello"}]
    a = await client.complete(model="fast", messages=msgs)
    b = await client.complete(model="fast", messages=msgs)
    assert a.text == b.text == "r1"
    assert inner.calls == 1


async def test_a_different_prompt_is_not_served_from_cache():
    inner = Counting()
    client = CachedLLMClient(inner, MemoryKV())
    await client.complete(model="fast", messages=[{"role": "user", "content": "a"}])
    await client.complete(model="fast", messages=[{"role": "user", "content": "b"}])
    assert inner.calls == 2


def test_cache_key_is_stable_regardless_of_dict_ordering():
    a = prompt_cache_key("fast", [{"role": "user", "content": "x"}])
    b = prompt_cache_key("fast", [{"content": "x", "role": "user"}])
    assert a == b


def test_cache_key_separates_models():
    assert (prompt_cache_key("fast", [{"role": "user", "content": "x"}])
            != prompt_cache_key("reasoning", [{"role": "user", "content": "x"}]))


async def test_a_json_mode_call_is_not_served_a_non_json_cached_response():
    """A plain-text response cached for json_mode=False must never be served to
    a later json_mode=True caller — that caller would never reach the provider
    with response_format set, converting a cache hit into a validation
    failure downstream (Task 2.3's repair loop)."""
    inner = Counting()
    client = CachedLLMClient(inner, MemoryKV())
    msgs = [{"role": "user", "content": "hello"}]
    await client.complete(model="fast", messages=msgs, json_mode=False)
    b = await client.complete(model="fast", messages=msgs, json_mode=True)
    assert inner.calls == 2
    assert b.text == "r2"


async def test_differing_temperatures_do_not_share_a_cache_entry():
    inner = Counting()
    client = CachedLLMClient(inner, MemoryKV())
    msgs = [{"role": "user", "content": "hello"}]
    await client.complete(model="fast", messages=msgs, temperature=0.0)
    b = await client.complete(model="fast", messages=msgs, temperature=0.7)
    assert inner.calls == 2
    assert b.text == "r2"


def test_cache_key_separates_json_mode():
    assert (prompt_cache_key("fast", [{"role": "user", "content": "x"}], json_mode=False)
            != prompt_cache_key("fast", [{"role": "user", "content": "x"}], json_mode=True))


def test_cache_key_separates_temperature():
    assert (prompt_cache_key("fast", [{"role": "user", "content": "x"}], temperature=0.0)
            != prompt_cache_key("fast", [{"role": "user", "content": "x"}], temperature=0.7))
