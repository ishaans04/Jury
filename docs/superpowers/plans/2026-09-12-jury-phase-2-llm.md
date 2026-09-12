# Phase 2 — LLM Layer, Offline Transport, Tracing

> **Parent:** [master plan](2026-09-12-jury-implementation.md) · **Read Global Constraints there first.**
> **PRD:** §15 (LLM layer), §15.3 (structured-output mitigations), §11.2 dec. 8–9, §17.3 (idempotency), §18 (failure modes)

**Phase goal:** A gateway that turns an unreliable open-weight model into a reliable typed-record producer, plus the fixture transport that lets every subsequent phase be verified with an empty `.env`, plus the trace table that replaces external observability.

**Why this comes before the chairs:** PRD §25 rates *"open-weight structured-output unreliability"* as **High** severity and PRD §15.3 calls it *"the single largest reliability risk in the build."* Building a chair on top of an unprotected LLM call would mean discovering that risk five times instead of once.

**Gate:** `JURY_OFFLINE=1 uv run pytest tests/llm -q` green with **no environment variables set**, and a repair-loop test proving all five §15.3 escalation stages fire in order.

---

## File structure

| Path | Responsibility |
|---|---|
| `jury/llm/models.py` | The single model-ID config map (PRD §15.1) |
| `jury/llm/gateway.py` | LiteLLM call, fallback chain, retry, budget accounting |
| `jury/llm/structured.py` | The five-stage repair loop (PRD §15.3) |
| `jury/llm/prompts.py` | Prompt registry — schema embedded in every prompt |
| `jury/llm/cache.py` | Prompt-hash response cache |
| `jury/transport/protocols.py` | `SearchClient`, `FetchClient`, `LLMClient`, `KV` Protocols |
| `jury/transport/fixtures.py` | Fixture implementations + recorder |
| `jury/transport/factory.py` | `build_transports(settings) -> Transports` |
| `jury/transport/kv.py` | Upstash REST KV + in-memory fallback |
| `jury/tracing/events.py` | `run_events` writer + `@traced` decorator |
| `jury/db/pool.py` | Connection pool (the only module that opens one) |
| `tests/fixtures/llm/*.json` | Recorded LLM responses |
| `tests/llm/test_gateway.py` | Fallback, retry, budget |
| `tests/llm/test_structured.py` | Five-stage repair escalation |
| `tests/llm/test_cache.py` | Prompt-hash caching |
| `tests/llm/test_offline.py` | Empty-env operation |
| `tests/tracing/test_events.py` | Trace row shape |

---

### Task 2.1: Transport protocols and the offline factory

**Files:**
- Create: `jury/transport/__init__.py`, `protocols.py`, `fixtures.py`, `factory.py`, `kv.py`
- Test: `tests/llm/test_offline.py`

**Interfaces:**
- Produces:
  - `class LLMClient(Protocol): async def complete(self, *, model: str, messages: list[dict], json_mode: bool = False, temperature: float = 0.0) -> LLMResponse`
  - `LLMResponse` dataclass: `text: str`, `model: str`, `prompt_tokens: int`, `completion_tokens: int`
  - `class SearchClient(Protocol): async def search(self, *, provider: str, query: str, limit: int = 10) -> list[SearchHit]`
  - `SearchHit` dataclass: `url: str`, `title: str`, `snippet: str`
  - `class FetchClient(Protocol): async def fetch(self, url: str) -> FetchResult`
  - `FetchResult` dataclass: `url: str`, `status: int`, `text: str`, `content_type: str`, `tier_hint: str`
  - `class KV(Protocol): async def get(k) -> str | None; async def set(k, v, ttl_s) -> None; async def incr_bucket(k, limit, window_s) -> bool`
  - `Transports` dataclass: `llm: LLMClient`, `search: SearchClient`, `fetch: FetchClient`, `kv: KV`, `offline: bool`
  - `build_transports(settings: Settings) -> Transports`

**Rule (spec §3):** offline substitutes **transport**, never **logic**. A fixture returns a canned HTTP body; it never returns a canned verdict, strength, breakpoint or conflict.

- [ ] **Step 1: Write the failing test**

`apps/api/tests/llm/test_offline.py`:
```python
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
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/api && uv run pytest tests/llm/test_offline.py -v
```
Expected: FAIL — `No module named 'jury.transport'`.

- [ ] **Step 3: Write `jury/transport/protocols.py`**

```python
"""Transport boundaries. Every outbound call in Jury crosses one of these.

Spec §3: offline mode swaps the implementation, never the logic above it.
"""
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True, slots=True)
class SearchHit:
    url: str
    title: str
    snippet: str


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    status: int
    text: str
    content_type: str = "text/html"
    tier_hint: str = ""


@runtime_checkable
class LLMClient(Protocol):
    async def complete(self, *, model: str, messages: list[dict],
                       json_mode: bool = False,
                       temperature: float = 0.0) -> LLMResponse: ...


@runtime_checkable
class SearchClient(Protocol):
    async def search(self, *, provider: str, query: str,
                     limit: int = 10) -> list[SearchHit]: ...


@runtime_checkable
class FetchClient(Protocol):
    async def fetch(self, url: str) -> FetchResult: ...


@runtime_checkable
class KV(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_s: int) -> None: ...
    async def incr_bucket(self, key: str, limit: int, window_s: int) -> bool: ...


@dataclass(frozen=True, slots=True)
class Transports:
    llm: LLMClient
    search: SearchClient
    fetch: FetchClient
    kv: KV
    offline: bool
```

- [ ] **Step 4: Write `jury/transport/kv.py`**

```python
"""Key-value transport: Upstash REST when configured, in-process otherwise.

Used for the search cache, fetch dedup, embedding cache, per-provider token
buckets and node idempotency keys (PRD §10, §17.2, §17.3).
"""
import time

import httpx


class MemoryKV:
    """In-process fallback. Correct for a single container and for tests."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}
        self._buckets: dict[str, list[float]] = {}

    async def get(self, key: str) -> str | None:
        hit = self._data.get(key)
        if hit is None:
            return None
        value, expires = hit
        if expires and expires < time.monotonic():
            del self._data[key]
            return None
        return value

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        self._data[key] = (value, time.monotonic() + ttl_s if ttl_s else 0.0)

    async def incr_bucket(self, key: str, limit: int, window_s: int) -> bool:
        """Sliding-window token bucket. False means the budget is spent."""
        now = time.monotonic()
        window = self._buckets.setdefault(key, [])
        window[:] = [t for t in window if now - t < window_s]
        if len(window) >= limit:
            return False
        window.append(now)
        return True


class UpstashKV:
    def __init__(self, url: str, token: str) -> None:
        self._url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}

    async def _cmd(self, *args: str | int) -> dict:
        path = "/".join(str(a) for a in args)
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{self._url}/{path}", headers=self._headers)
            r.raise_for_status()
            return r.json()

    async def get(self, key: str) -> str | None:
        return (await self._cmd("get", key)).get("result")

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        await self._cmd("set", key, value, "ex", ttl_s)

    async def incr_bucket(self, key: str, limit: int, window_s: int) -> bool:
        count = (await self._cmd("incr", key)).get("result", 0)
        if count == 1:
            await self._cmd("expire", key, window_s)
        return int(count) <= limit
```

- [ ] **Step 5: Write `jury/transport/fixtures.py`**

Fixtures are content-addressed by a hash of the request, so the same prompt always replays the same response — which is what makes offline runs deterministic and diffable.

```python
"""Fixture transports. Spec §3.

Responses are content-addressed by request hash and stored under
tests/fixtures/. A miss is a loud failure in tests and a documented absence in
a demo run — never a silently invented answer.
"""
import hashlib
import json
import pathlib

from jury.transport.protocols import FetchResult, LLMResponse, SearchHit

FIXTURE_ROOT = pathlib.Path(__file__).parents[2] / "tests" / "fixtures"


def request_key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]


def _load(kind: str, key: str) -> dict | None:
    path = FIXTURE_ROOT / kind / f"{key}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save(kind: str, key: str, payload: dict) -> None:
    path = FIXTURE_ROOT / kind / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class FixtureLLMClient:
    """Replays recorded completions. Falls back to a schema-shaped default so a
    demo run degrades to 'less evidence' rather than crashing (PRD §18)."""

    def __init__(self, default_text: str = "{}") -> None:
        self._default = default_text

    async def complete(self, *, model: str, messages: list[dict],
                       json_mode: bool = False,
                       temperature: float = 0.0) -> LLMResponse:
        prompt = json.dumps(messages, sort_keys=True)
        rec = _load("llm", request_key(model, prompt))
        text = rec["text"] if rec else self._default
        return LLMResponse(text=text, model=f"fixture/{model}",
                           prompt_tokens=len(prompt) // 4,
                           completion_tokens=len(text) // 4)


class FixtureSearchClient:
    async def search(self, *, provider: str, query: str,
                     limit: int = 10) -> list[SearchHit]:
        rec = _load("search", request_key(provider, query))
        hits = rec["hits"] if rec else []
        return [SearchHit(**h) for h in hits[:limit]]


class FixtureFetchClient:
    async def fetch(self, url: str) -> FetchResult:
        rec = _load("fetch", request_key(url))
        if rec is None:
            # A fixture miss is a documented absence: 404 means no evidence row
            # gets written, which is exactly P1's behaviour.
            return FetchResult(url=url, status=404, text="", content_type="")
        return FetchResult(url=url, status=rec.get("status", 200),
                           text=rec.get("text", ""),
                           content_type=rec.get("content_type", "text/html"))


class RecordingLLMClient:
    """Wraps a live client and writes fixtures. Used to pre-warm the demo cache
    (PRD §21.3 step 7) and to build the recorded fallback run (PRD §25)."""

    def __init__(self, inner) -> None:
        self._inner = inner

    async def complete(self, **kw) -> LLMResponse:
        r = await self._inner.complete(**kw)
        prompt = json.dumps(kw["messages"], sort_keys=True)
        _save("llm", request_key(kw["model"], prompt), {"text": r.text})
        return r
```

- [ ] **Step 6: Write `jury/transport/factory.py`**

```python
"""Transport selection. One place decides live vs fixture."""
from jury.settings import Settings
from jury.transport.fixtures import (
    FixtureFetchClient, FixtureLLMClient, FixtureSearchClient,
)
from jury.transport.kv import MemoryKV, UpstashKV
from jury.transport.protocols import Transports


def build_transports(settings: Settings) -> Transports:
    kv = (UpstashKV(settings.upstash_redis_rest_url, settings.upstash_redis_rest_token)
          if settings.upstash_redis_rest_url and settings.upstash_redis_rest_token
          else MemoryKV())

    if settings.offline:
        return Transports(llm=FixtureLLMClient(), search=FixtureSearchClient(),
                          fetch=FixtureFetchClient(), kv=kv, offline=True)

    # Imported lazily so an offline environment never needs the live deps.
    from jury.llm.gateway import LiveLLMClient
    from jury.retrieval.fetch import LiveFetchClient
    from jury.retrieval.search import LiveSearchClient

    return Transports(llm=LiveLLMClient(settings), search=LiveSearchClient(settings, kv),
                      fetch=LiveFetchClient(settings, kv), kv=kv, offline=False)
```

Note: Phase 2 must create minimal real `LiveLLMClient` (Task 2.2). `LiveSearchClient` / `LiveFetchClient` land in Phase 3; until then the lazy import means only a live-mode run touches them, and `test_a_real_key_with_offline_zero_selects_live_transports` must be marked `xfail` until Phase 3 — or better, split: that test asserts only on `t.llm`, which Phase 2 does provide. Keep it asserting only `t.llm`.

- [ ] **Step 7: Run to verify it passes**

```bash
cd apps/api && uv run pytest tests/llm/test_offline.py -v
```
Expected: 8 passed.

- [ ] **Step 8: Commit**

```bash
git add apps/api/jury/transport apps/api/tests/llm/test_offline.py
git commit -m "feat(transport): protocol boundaries with fixture and live selection"
```

---

### Task 2.2: Gateway — model map, fallback chain, budget

**Files:**
- Create: `jury/llm/__init__.py`, `jury/llm/models.py`, `jury/llm/gateway.py`, `jury/llm/cache.py`
- Test: `tests/llm/test_gateway.py`, `tests/llm/test_cache.py`

**Interfaces:**
- Produces:
  - `ModelRole = Literal["reasoning", "fast", "fallback"]`
  - `resolve_model(role: ModelRole, settings: Settings) -> str`
  - `FALLBACK_CHAIN: dict[ModelRole, tuple[ModelRole, ...]]`
  - `class LiveLLMClient` implementing `LLMClient`
  - `class BudgetExceeded(Exception)`
  - `CachedLLMClient(inner: LLMClient, kv: KV, ttl_s: int = 86400)`
  - `prompt_cache_key(model: str, messages: list[dict]) -> str`

**PRD §15.1 requirement, verbatim:** *"Groq deprecates and renames models frequently. Resolve actual model IDs in the Groq console at build time and keep them in a single config map — do not hardcode them across the codebase."*

- [ ] **Step 1: Write the failing tests**

`apps/api/tests/llm/test_gateway.py`:
```python
import pytest

from jury.llm.gateway import BudgetExceeded, LiveLLMClient
from jury.llm.models import FALLBACK_CHAIN, DEFAULT_MODEL_IDS, resolve_model
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
```

`apps/api/tests/llm/test_cache.py`:
```python
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd apps/api && uv run pytest tests/llm/test_gateway.py tests/llm/test_cache.py -v
```
Expected: FAIL — modules missing.

- [ ] **Step 3: Write `jury/llm/models.py`**

```python
"""The single model-ID config map. PRD §15.1.

Groq deprecates and renames models frequently. Resolve the real IDs in the Groq
console at build time and set them via env; these defaults are a documented
starting point, not a guarantee. Nothing else in the codebase may hardcode a
model name.
"""
from typing import Literal

from jury.settings import Settings

ModelRole = Literal["reasoning", "fast", "fallback"]

# Candidates named in PRD §15.1. VERIFY IN THE GROQ CONSOLE before relying on them.
DEFAULT_MODEL_IDS: dict[ModelRole, str] = {
    "reasoning": "groq/llama-3.3-70b-versatile",
    "fast": "groq/llama-3.1-8b-instant",
    "fallback": "groq/openai/gpt-oss-120b",
}

# PRD §15.2: model-level fallback within the provider rather than failing the run.
FALLBACK_CHAIN: dict[ModelRole, tuple[ModelRole, ...]] = {
    "reasoning": ("reasoning", "fast", "fallback"),
    "fast": ("fast", "fallback"),
    "fallback": ("fallback",),
}

# PRD §15.1 task-to-role assignment.
TASK_ROLES: dict[str, ModelRole] = {
    "assumption_extraction": "reasoning",
    "archetype_detection": "fast",
    "claim_structuring": "fast",      # the dominant call count
    "scope_typing": "fast",
    "cross_examination": "reasoning",
    "jury_rationale": "reasoning",    # the model writes prose; the score is computed
    "experiment_instructions": "fast",
}

_ENV_KEYS: dict[ModelRole, str] = {
    "reasoning": "llm_model_reasoning",
    "fast": "llm_model_fast",
    "fallback": "llm_model_fallback",
}


def resolve_model(role: ModelRole, settings: Settings) -> str:
    override = getattr(settings, _ENV_KEYS[role], None)
    return override or DEFAULT_MODEL_IDS[role]
```

- [ ] **Step 4: Write `jury/llm/gateway.py`**

```python
"""LiteLLM gateway. PRD §11.2 decision 8 — retained even with a single provider.

Earns its place four ways: model-level fallback within Groq, unified retry and
backoff for 429s across all seven call sites, budget caps that feed run_events,
and a one-line provider swap if Groq degrades during judging (PRD §15.2).
"""
import asyncio

from litellm import acompletion

from jury.llm.models import FALLBACK_CHAIN, ModelRole, resolve_model
from jury.settings import Settings
from jury.transport.protocols import LLMResponse

MAX_LLM_CALLS_PER_RUN = 120          # PRD §17.2
_RETRYABLE = ("429", "rate_limit", "overloaded", "timeout", "502", "503", "504")
_BACKOFF_S = (0.5, 1.5, 3.0)


class BudgetExceeded(RuntimeError):
    """Raised when a run exhausts its LLM call budget (PRD §17.2)."""


def _is_retryable(err: Exception) -> bool:
    text = str(err).lower()
    return any(token in text for token in _RETRYABLE)


class LiveLLMClient:
    def __init__(self, settings: Settings,
                 max_calls: int = MAX_LLM_CALLS_PER_RUN) -> None:
        self._settings = settings
        self._max_calls = max_calls
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    async def complete(self, *, model: str, messages: list[dict],
                       json_mode: bool = False,
                       temperature: float = 0.0) -> LLMResponse:
        """`model` is a ROLE name ('reasoning' | 'fast' | 'fallback'), not an ID.

        Walks the role's fallback chain; within each role, retries retryable
        errors with backoff before degrading to the next tier.
        """
        if self.calls >= self._max_calls:
            raise BudgetExceeded(
                f"run exhausted its {self._max_calls}-call LLM budget")

        role: ModelRole = model if model in FALLBACK_CHAIN else "fast"
        last: Exception | None = None

        for tier in FALLBACK_CHAIN[role]:
            model_id = resolve_model(tier, self._settings)
            for delay in (*_BACKOFF_S, None):
                try:
                    kwargs: dict = {
                        "model": model_id,
                        "messages": messages,
                        "temperature": temperature,
                        "api_key": self._settings.groq_api_key,
                    }
                    if json_mode:
                        kwargs["response_format"] = {"type": "json_object"}
                    raw = await acompletion(**kwargs)
                except Exception as err:                 # noqa: BLE001
                    last = err
                    if delay is None or not _is_retryable(err):
                        break
                    await asyncio.sleep(delay)
                    continue

                self.calls += 1
                usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
                pt = int(usage.get("prompt_tokens", 0))
                ct = int(usage.get("completion_tokens", 0))
                self.prompt_tokens += pt
                self.completion_tokens += ct
                content = raw["choices"][0]["message"]["content"] or ""
                return LLMResponse(text=content, model=model_id,
                                   prompt_tokens=pt, completion_tokens=ct)

        raise RuntimeError(f"all models in chain for role '{role}' failed") from last
```

- [ ] **Step 5: Write `jury/llm/cache.py`**

```python
"""Prompt-hash response cache. PRD §15.3 single-point-of-failure mitigation."""
import hashlib
import json

from jury.transport.protocols import KV, LLMClient, LLMResponse


def prompt_cache_key(model: str, messages: list[dict]) -> str:
    payload = json.dumps({"m": model, "p": messages}, sort_keys=True)
    return "llm:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CachedLLMClient:
    """Wraps any LLMClient. A cache hit costs no tokens and no quota, which is
    what makes the pre-warmed demo run survive a Groq outage (PRD §25)."""

    def __init__(self, inner: LLMClient, kv: KV, ttl_s: int = 86_400) -> None:
        self._inner = inner
        self._kv = kv
        self._ttl = ttl_s

    async def complete(self, *, model: str, messages: list[dict],
                       json_mode: bool = False,
                       temperature: float = 0.0) -> LLMResponse:
        key = prompt_cache_key(model, messages)
        cached = await self._kv.get(key)
        if cached is not None:
            rec = json.loads(cached)
            return LLMResponse(text=rec["text"], model=rec["model"],
                               prompt_tokens=0, completion_tokens=0)
        r = await self._inner.complete(model=model, messages=messages,
                                       json_mode=json_mode, temperature=temperature)
        await self._kv.set(key, json.dumps({"text": r.text, "model": r.model}),
                           self._ttl)
        return r
```

- [ ] **Step 6: Run to verify they pass**

```bash
cd apps/api && uv run pytest tests/llm/test_gateway.py tests/llm/test_cache.py -v
```
Expected: 9 + 4 passed.

- [ ] **Step 7: Commit**

```bash
git add apps/api/jury/llm apps/api/tests/llm/test_gateway.py apps/api/tests/llm/test_cache.py
git commit -m "feat(llm): gateway with fallback chain, budget cap and prompt-hash cache"
```

---

### Task 2.3: The five-stage repair loop

**Files:**
- Create: `jury/llm/structured.py`, `jury/llm/prompts.py`
- Test: `tests/llm/test_structured.py`

**Interfaces:**
- Produces:
  - `async def structured(client: LLMClient, *, role: str, prompt: str, schema: type[BaseModel], trace: TraceSink | None = None) -> BaseModel | None`
  - `async def structured_many(...) -> list[BaseModel]`
  - `RepairStage = Literal["initial", "repair", "field_split", "dropped"]`
  - `class RepairReport` dataclass: `stages: list[RepairStage]`, `value: BaseModel | None`, `errors: list[str]`
  - `schema_prompt_block(schema: type[BaseModel]) -> str`

**The five mandatory mitigations (PRD §15.3, verbatim):**
1. JSON mode enabled on every structured call.
2. Pydantic validation on every response, with the schema also embedded in the prompt.
3. A repair loop: on validation failure, re-prompt once with the validation error and the offending output attached.
4. On second failure, downgrade the task — split one extraction call into several narrower single-field calls.
5. On third failure, drop the claim and write an `error` row to `run_events`. *"A dropped claim is acceptable; a malformed ledger row is not."*

- [ ] **Step 1: Write the failing test**

`apps/api/tests/llm/test_structured.py`:
```python
import pytest
from pydantic import BaseModel, Field

from jury.llm.structured import schema_prompt_block, structured_report
from jury.transport.protocols import LLMResponse


class Tiny(BaseModel):
    name: str
    count: int = Field(ge=0)


class Scripted:
    """Returns a scripted sequence of responses, one per call."""

    def __init__(self, *texts: str) -> None:
        self._texts = list(texts)
        self.prompts: list[str] = []
        self.json_modes: list[bool] = []

    async def complete(self, *, model, messages, json_mode=False, temperature=0.0):
        self.prompts.append(messages[-1]["content"])
        self.json_modes.append(json_mode)
        text = self._texts.pop(0) if self._texts else "{}"
        return LLMResponse(text=text, model=model, prompt_tokens=1, completion_tokens=1)


# ── stage 1: it just works ──────────────────────────────────────────────────
async def test_valid_first_response_needs_no_repair():
    client = Scripted('{"name":"a","count":2}')
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.value == Tiny(name="a", count=2)
    assert rep.stages == ["initial"]


async def test_json_mode_is_always_enabled():
    """PRD §15.3 mitigation 1: JSON mode on EVERY structured call."""
    client = Scripted('{"name":"a","count":2}')
    await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert client.json_modes == [True]


async def test_the_schema_is_embedded_in_the_prompt():
    """PRD §15.3 mitigation 2: the schema is also embedded in the prompt."""
    client = Scripted('{"name":"a","count":2}')
    await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert "count" in client.prompts[0] and "name" in client.prompts[0]


async def test_fenced_json_is_tolerated():
    """Small models wrap JSON in markdown fences constantly."""
    client = Scripted('```json\n{"name":"a","count":2}\n```')
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.value == Tiny(name="a", count=2)


async def test_prose_wrapped_json_is_extracted():
    client = Scripted('Sure! Here is the record: {"name":"a","count":2} Hope that helps.')
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.value == Tiny(name="a", count=2)


# ── stage 2: the repair re-prompt ───────────────────────────────────────────
async def test_invalid_then_valid_repairs_on_the_second_call():
    client = Scripted('{"name":"a","count":-1}', '{"name":"a","count":1}')
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.value == Tiny(name="a", count=1)
    assert rep.stages == ["initial", "repair"]


async def test_the_repair_prompt_carries_the_error_and_the_offending_output():
    """PRD §15.3 mitigation 3: re-prompt with the validation error AND the
    offending output attached."""
    client = Scripted('{"name":"a","count":-1}', '{"name":"a","count":1}')
    await structured_report(client, role="fast", prompt="go", schema=Tiny)
    repair_prompt = client.prompts[1]
    assert '"count":-1' in repair_prompt.replace(" ", "")
    assert "count" in repair_prompt
    assert "greater than or equal" in repair_prompt.lower() or "ge" in repair_prompt


async def test_repair_is_attempted_exactly_once():
    client = Scripted('{"bad":1}', '{"bad":2}', '{"name":"a","count":1}')
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.stages.count("repair") == 1


# ── stage 3: field-split downgrade ─────────────────────────────────────────
async def test_second_failure_downgrades_to_single_field_calls():
    """PRD §15.3 mitigation 4: split one extraction into narrower single-field
    calls, which small models handle far more reliably."""
    client = Scripted('{"bad":1}', '{"still":"bad"}', '"a"', "2")
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.stages == ["initial", "repair", "field_split"]
    assert rep.value == Tiny(name="a", count=2)


async def test_field_split_prompts_ask_for_one_field_each():
    client = Scripted('{"bad":1}', '{"still":"bad"}', '"a"', "2")
    await structured_report(client, role="fast", prompt="go", schema=Tiny)
    split_prompts = client.prompts[2:]
    assert len(split_prompts) == 2
    assert "name" in split_prompts[0] and "count" not in split_prompts[0]
    assert "count" in split_prompts[1]


# ── stage 4: drop the claim ────────────────────────────────────────────────
async def test_third_failure_drops_the_claim_and_returns_none():
    """PRD §15.3 mitigation 5: a dropped claim is acceptable; a malformed
    ledger row is not."""
    client = Scripted('{"bad":1}', '{"bad":2}', "nonsense", "garbage")
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.value is None
    assert rep.stages[-1] == "dropped"


async def test_dropping_a_claim_records_an_error_for_the_trace():
    """The error row is what makes a dropped claim visible in F17's viewer
    rather than silently vanishing."""
    client = Scripted('{"bad":1}', '{"bad":2}', "nonsense", "garbage")
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.errors, "a dropped claim must carry the reason it was dropped"


async def test_a_dropped_claim_never_returns_a_partial_object():
    """A half-populated record is exactly the malformed ledger row P1 forbids."""
    client = Scripted('{"name":"a"}', '{"name":"a"}', '"a"', "not-a-number")
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.value is None


async def test_escalation_order_is_never_skipped():
    client = Scripted('{"bad":1}', '{"bad":2}', "x", "y")
    rep = await structured_report(client, role="fast", prompt="go", schema=Tiny)
    assert rep.stages == ["initial", "repair", "field_split", "dropped"]


# ── helper ─────────────────────────────────────────────────────────────────
def test_schema_prompt_block_lists_every_field_and_its_type():
    block = schema_prompt_block(Tiny)
    assert "name" in block and "count" in block
    assert "string" in block.lower() and "integer" in block.lower()
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/api && uv run pytest tests/llm/test_structured.py -v
```
Expected: FAIL — module missing.

- [ ] **Step 3: Write `jury/llm/structured.py`**

```python
"""Structured-output enforcement. PRD §15.3 — all five mitigations, mandatory.

Open-weight models are weaker at strict structured output than frontier models.
Since every chair's output contract is a typed JSON record (PRD §6.1), this is
the single largest reliability risk in the build. This module is the mitigation.

Escalation, in order and never skipped:
    initial -> repair -> field_split -> dropped
"""
import json
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ValidationError

from jury.transport.protocols import LLMClient

RepairStage = Literal["initial", "repair", "field_split", "dropped"]

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(slots=True)
class RepairReport:
    value: BaseModel | None
    stages: list[RepairStage] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def schema_prompt_block(schema: type[BaseModel]) -> str:
    """Render the schema for embedding in the prompt (mitigation 2).

    Small models follow an explicit field list far better than a prose
    description of the same thing.
    """
    js = schema.model_json_schema()
    lines = ["Return ONE JSON object with exactly these keys:"]
    required = set(js.get("required", []))
    for name, spec in js.get("properties", {}).items():
        kind = spec.get("type") or "any"
        if "anyOf" in spec:
            kind = " | ".join(o.get("type", "null") for o in spec["anyOf"])
        bound = ""
        if "minimum" in spec:
            bound += f", minimum {spec['minimum']}"
        if "maximum" in spec:
            bound += f", maximum {spec['maximum']}"
        if "enum" in spec:
            bound += f", one of {spec['enum']}"
        flag = "required" if name in required else "optional"
        lines.append(f'  "{name}": {kind} ({flag}{bound})')
    lines.append("No prose. No markdown fences. No trailing commentary.")
    return "\n".join(lines)


def _extract_json(text: str) -> str:
    """Small models wrap JSON in fences and chatter. Recover the object."""
    fenced = _FENCE.search(text)
    if fenced:
        return fenced.group(1)
    obj = _OBJECT.search(text)
    return obj.group(0) if obj else text.strip()


def _parse(text: str, schema: type[BaseModel]) -> tuple[BaseModel | None, str | None]:
    try:
        return schema.model_validate_json(_extract_json(text)), None
    except (ValidationError, ValueError) as err:
        return None, str(err)


def _coerce_scalar(text: str) -> object:
    """A single-field answer may arrive quoted, fenced, or bare."""
    raw = _extract_json(text).strip().strip("`")
    try:
        return json.loads(raw)
    except ValueError:
        return raw.strip('"').strip()


async def structured_report(
    client: LLMClient, *, role: str, prompt: str, schema: type[BaseModel],
) -> RepairReport:
    """Produce a validated instance of `schema`, or None having tried everything."""
    report = RepairReport(value=None)
    block = schema_prompt_block(schema)

    # ── stage 1: initial, JSON mode on, schema embedded ─────────────────────
    report.stages.append("initial")
    first = await client.complete(
        model=role, messages=[{"role": "user", "content": f"{prompt}\n\n{block}"}],
        json_mode=True)
    value, error = _parse(first.text, schema)
    if value is not None:
        report.value = value
        return report
    report.errors.append(error or "unparseable")

    # ── stage 2: repair — error and offending output attached ───────────────
    report.stages.append("repair")
    repair_prompt = (
        f"{prompt}\n\n{block}\n\n"
        f"Your previous answer was rejected by schema validation.\n"
        f"Previous answer:\n{first.text}\n\n"
        f"Validation error:\n{error}\n\n"
        f"Return corrected JSON only.")
    second = await client.complete(
        model=role, messages=[{"role": "user", "content": repair_prompt}],
        json_mode=True)
    value, error2 = _parse(second.text, schema)
    if value is not None:
        report.value = value
        return report
    report.errors.append(error2 or "unparseable")

    # ── stage 3: field-split downgrade ──────────────────────────────────────
    report.stages.append("field_split")
    js = schema.model_json_schema()
    assembled: dict[str, object] = {}
    for name, spec in js.get("properties", {}).items():
        kind = spec.get("type") or "any"
        ask = (f"{prompt}\n\n"
               f'Answer with ONLY the value for the single field "{name}" '
               f"({kind}). No object, no key, no prose — just the value.")
        one = await client.complete(model=role,
                                    messages=[{"role": "user", "content": ask}],
                                    json_mode=False)
        assembled[name] = _coerce_scalar(one.text)

    try:
        report.value = schema.model_validate(assembled)
        return report
    except ValidationError as err:
        report.errors.append(str(err))

    # ── stage 4: drop the claim ─────────────────────────────────────────────
    # A dropped claim is acceptable; a malformed ledger row is not (PRD §15.3).
    report.stages.append("dropped")
    report.value = None
    return report


async def structured(client: LLMClient, *, role: str, prompt: str,
                     schema: type[BaseModel]) -> BaseModel | None:
    """Convenience wrapper when the caller does not need the escalation trace."""
    return (await structured_report(client, role=role, prompt=prompt,
                                    schema=schema)).value
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd apps/api && uv run pytest tests/llm/test_structured.py -v
```
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/api/jury/llm/structured.py apps/api/tests/llm/test_structured.py
git commit -m "feat(llm): five-stage structured-output repair loop"
```

---

### Task 2.4: `run_events` tracing

**Files:**
- Create: `jury/db/pool.py`, `jury/tracing/events.py`
- Test: `tests/tracing/test_events.py`

**Interfaces:**
- Produces:
  - `class TraceSink` with `async def emit(self, *, node: str, event: str, detail: dict | None = None, latency_ms: int | None = None) -> None`
  - `@traced(node: str)` async decorator emitting `node_start` / `node_end` / `error` with measured latency
  - `EVENT_KINDS = ("node_start","node_end","llm_call","tool_call","fetch","error","interrupt")`

**Why it matters (PRD §11.2 dec. 9):** *"showing judges the trace inside the product proves the pipeline is real."* It replaces Langfuse/LangSmith entirely.

- [ ] **Step 1: Write the failing test**

`apps/api/tests/tracing/test_events.py`:
```python
import pytest

from jury.tracing.events import EVENT_KINDS, MemoryTraceSink, traced


async def test_every_event_kind_matches_the_db_check_constraint():
    assert set(EVENT_KINDS) == {"node_start", "node_end", "llm_call", "tool_call",
                                "fetch", "error", "interrupt"}


async def test_traced_emits_start_and_end_with_latency():
    sink = MemoryTraceSink()

    @traced("archetype")
    async def node(state, *, trace):
        return {"ok": True}

    await node({}, trace=sink)
    kinds = [r["event"] for r in sink.rows]
    assert kinds == ["node_start", "node_end"]
    assert sink.rows[1]["latency_ms"] >= 0
    assert sink.rows[0]["node"] == "archetype"


async def test_traced_emits_an_error_row_and_reraises():
    sink = MemoryTraceSink()

    @traced("boom")
    async def node(state, *, trace):
        raise ValueError("nope")

    with pytest.raises(ValueError):
        await node({}, trace=sink)
    kinds = [r["event"] for r in sink.rows]
    assert kinds == ["node_start", "error"]
    assert "nope" in sink.rows[1]["detail"]["error"]


async def test_llm_call_rows_carry_token_counts():
    """PRD §11.2 dec. 9: one row per tool call, latency, token count."""
    sink = MemoryTraceSink()
    await sink.emit(node="market", event="llm_call",
                    detail={"model": "groq/x", "prompt_tokens": 120,
                            "completion_tokens": 40}, latency_ms=310)
    row = sink.rows[0]
    assert row["detail"]["prompt_tokens"] == 120
    assert row["latency_ms"] == 310


async def test_an_unknown_event_kind_is_rejected_before_it_reaches_the_db():
    sink = MemoryTraceSink()
    with pytest.raises(ValueError):
        await sink.emit(node="market", event="vibes")


async def test_fetch_rows_record_url_and_status():
    sink = MemoryTraceSink()
    await sink.emit(node="market", event="fetch",
                    detail={"url": "https://x.test/p", "status": 200, "ms": 84})
    assert sink.rows[0]["detail"]["status"] == 200


async def test_interrupt_is_traceable_so_the_hearing_pause_is_visible():
    sink = MemoryTraceSink()
    await sink.emit(node="hearing", event="interrupt",
                    detail={"reason": "awaiting founder confirmation"})
    assert sink.rows[0]["event"] == "interrupt"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd apps/api && uv run pytest tests/tracing/test_events.py -v
```
Expected: FAIL — module missing.

- [ ] **Step 3: Write `jury/tracing/events.py`**

```python
"""In-app tracing. PRD §11.2 decision 9 — replaces Langfuse/LangSmith.

One row per node entry/exit, tool call, latency, token count and error. Costs
one table, removes a service, and doubles as a demo asset: showing judges the
trace inside the product proves the pipeline is real.
"""
import functools
import time
from typing import Any

EVENT_KINDS = ("node_start", "node_end", "llm_call", "tool_call",
               "fetch", "error", "interrupt")


class MemoryTraceSink:
    """Collects rows in process. Used by tests and by offline runs."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def emit(self, *, node: str, event: str, detail: dict | None = None,
                   latency_ms: int | None = None) -> None:
        if event not in EVENT_KINDS:
            raise ValueError(f"unknown event kind {event!r}; "
                             f"the db CHECK constraint would reject it")
        self.rows.append({"node": node, "event": event,
                          "detail": detail or {}, "latency_ms": latency_ms})


class PostgresTraceSink:
    """Writes to run_events. Insert-only and never in the request's critical path."""

    def __init__(self, pool, run_id: str) -> None:
        self._pool = pool
        self._run_id = run_id

    async def emit(self, *, node: str, event: str, detail: dict | None = None,
                   latency_ms: int | None = None) -> None:
        import json
        if event not in EVENT_KINDS:
            raise ValueError(f"unknown event kind {event!r}")
        async with self._pool.connection() as conn:
            await conn.execute(
                "insert into run_events (run_id, node, event, detail, latency_ms) "
                "values (%s, %s, %s, %s, %s)",
                (self._run_id, node, event, json.dumps(detail or {}), latency_ms))


def traced(node: str):
    """Wrap a graph node so entry, exit, latency and failure are all recorded.

    The wrapped function must accept a keyword-only `trace` argument.
    """
    def decorate(fn):
        @functools.wraps(fn)
        async def wrapper(*args, trace=None, **kwargs):
            if trace is None:
                return await fn(*args, **kwargs)
            await trace.emit(node=node, event="node_start")
            started = time.perf_counter()
            try:
                result = await fn(*args, trace=trace, **kwargs)
            except Exception as err:                      # noqa: BLE001
                await trace.emit(
                    node=node, event="error",
                    detail={"error": f"{type(err).__name__}: {err}"},
                    latency_ms=int((time.perf_counter() - started) * 1000))
                raise
            await trace.emit(
                node=node, event="node_end",
                latency_ms=int((time.perf_counter() - started) * 1000))
            return result
        return wrapper
    return decorate
```

Note: `traced` passes `trace` through to the wrapped function so a node can emit its own `llm_call` and `fetch` rows. Nodes that do not need it accept and ignore it.

- [ ] **Step 4: Write `jury/db/pool.py`**

```python
"""The only module that opens a database connection pool."""
from psycopg_pool import AsyncConnectionPool

from jury.settings import Settings

_pool: AsyncConnectionPool | None = None


def get_pool(settings: Settings) -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(settings.database_url, min_size=1, max_size=8,
                                    open=False)
    return _pool


async def open_pool(settings: Settings) -> AsyncConnectionPool:
    pool = get_pool(settings)
    await pool.open()
    return pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
```

- [ ] **Step 5: Run to verify it passes**

```bash
cd apps/api && uv run pytest tests/tracing/test_events.py -v
```
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/api/jury/tracing apps/api/jury/db apps/api/tests/tracing
git commit -m "feat(tracing): run_events sink and traced node decorator"
```

---

### Task 2.5: Phase gate — full suite with an empty environment

- [ ] **Step 1: Prove the empty-env claim**

```bash
cd apps/api && env -u GROQ_API_KEY -u BRAVE_API_KEY -u TAVILY_API_KEY \
  -u EXA_API_KEY -u UPSTASH_REDIS_REST_URL -u UPSTASH_REDIS_REST_TOKEN \
  JURY_OFFLINE=1 uv run pytest -q
```
Expected: everything green. On Windows PowerShell, use `$env:JURY_OFFLINE=1; uv run pytest -q` after confirming no key variables are set in the session.

- [ ] **Step 2: Confirm no test reaches the network**

```bash
cd apps/api && JURY_OFFLINE=1 uv run pytest -q -p no:cacheprovider
```
Add to `tests/conftest.py` an autouse fixture that patches `httpx.AsyncClient.request` to raise unless a test opts in with `@pytest.mark.network`. Run again and confirm green — that is the proof, not the intention.

- [ ] **Step 3: Append to `CHANGELOG.md` and push**

Record: the five §15.3 mitigations are implemented and individually tested; the model-ID map location; that offline mode is transport-only; and the `traced` `trace`-passthrough detail.

```bash
git add -A
git commit -m "test: enforce no-network default across the suite"
git push origin main
```

---

## Phase 2 exit criteria

- [ ] `build_transports` selects fixtures with zero credentials and live clients with a key
- [ ] Explicit `JURY_OFFLINE` overrides key presence in both directions
- [ ] Model IDs exist in **exactly one** map; env overrides it
- [ ] A 429 on `reasoning` degrades to `fast` then `fallback` rather than failing the run
- [ ] Exhausting the chain raises — it never invents an answer
- [ ] LLM call budget (120) enforced with `BudgetExceeded`
- [ ] JSON mode on **every** structured call, schema embedded in **every** prompt
- [ ] Repair escalation is exactly `initial → repair → field_split → dropped`, never skipped
- [ ] The repair prompt carries both the validation error and the offending output
- [ ] A dropped claim returns `None` with a recorded reason — **never a partial object**
- [ ] `run_events` rejects unknown event kinds before they reach the CHECK constraint
- [ ] `traced` records latency on success and an `error` row on failure, then re-raises
- [ ] Whole suite green with **no credentials set** and a network-blocking autouse fixture
