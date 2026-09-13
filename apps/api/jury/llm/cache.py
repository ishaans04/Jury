"""Prompt-hash response cache. PRD §15.3 single-point-of-failure mitigation."""
import hashlib
import json

from jury.transport.protocols import KV, LLMClient, LLMResponse


def prompt_cache_key(model: str, messages: list[dict], *,
                     json_mode: bool = False, temperature: float = 0.0) -> str:
    """Keyed on model + messages + json_mode + temperature.

    json_mode and temperature must be part of the key: a plain-text response
    cached for a non-JSON call must never be served to a later json_mode=True
    call for the same prompt (it would never reach the provider with
    response_format set), and a temperature=0.0 deterministic response is not
    interchangeable with a sampled one.
    """
    payload = json.dumps({"m": model, "p": messages,
                          "j": json_mode, "t": temperature}, sort_keys=True)
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
        key = prompt_cache_key(model, messages, json_mode=json_mode, temperature=temperature)
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
