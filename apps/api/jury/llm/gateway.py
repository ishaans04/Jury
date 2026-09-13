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

        Moves to the next tier in the role's fallback chain immediately on a
        retryable error: a different model has its own rate-limit bucket, so
        sleeping before switching buys nothing. Only the LAST tier — where
        there is nowhere further to fall back to — retries the same model with
        backoff before finally giving up. A non-retryable error never sleeps;
        it breaks out of the current tier immediately.

        The budget counter is incremented once per successful `complete()`
        call, not once per underlying HTTP attempt: retries and tier
        fallbacks are implementation detail of fulfilling one logical call, so
        they must not consume the budget more than once. A call that
        ultimately fails (raises) consumes none of the budget either — the
        cap exists to bound how many *answers* a run may draw on, not to
        penalise transient provider flakiness.
        """
        if self.calls >= self._max_calls:
            raise BudgetExceeded(
                f"run exhausted its {self._max_calls}-call LLM budget")

        role: ModelRole = model if model in FALLBACK_CHAIN else "fast"
        chain = FALLBACK_CHAIN[role]
        last: Exception | None = None

        for idx, tier in enumerate(chain):
            model_id = resolve_model(tier, self._settings)
            is_last_tier = idx == len(chain) - 1
            # Only the last tier retries in place (backoff then give up);
            # every earlier tier tries once and falls through on any failure.
            attempts = (*_BACKOFF_S, None) if is_last_tier else (None,)

            for delay in attempts:
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
