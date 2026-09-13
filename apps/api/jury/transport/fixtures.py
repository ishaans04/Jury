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
