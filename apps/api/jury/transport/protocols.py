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
