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
_BACKOFF_S = (0.5, 1.5, 3.0)          # last-tier retry-in-place backoff
_TRANSIENT_RETRY_S = 0.5              # one quick retry on a non-terminal tier

# Quota errors carry no useful signal for retrying the SAME model — the quota
# is what it is, so the only sensible move is to advance to the next tier.
_QUOTA = ("429", "rate_limit", "overloaded", "quota")
# Transient errors are network blips, not quota signals. A quick single retry
# at the preferred tier is cheap and likely to succeed, so an ordinary hiccup
# does not permanently downgrade the run's highest-value calls to a weaker
# model.
_TRANSIENT = ("timeout", "timed out", "502", "503", "504",
              "connection", "temporarily unavailable")


class BudgetExceeded(RuntimeError):
    """Raised when a run exhausts its LLM call budget (PRD §17.2)."""


def _classify(err: Exception) -> str:
    """Returns 'quota' | 'transient' | 'fatal'. Drives the per-tier retry policy."""
    text = str(err).lower()
    if any(t in text for t in _QUOTA):
        return "quota"
    if any(t in text for t in _TRANSIENT):
        return "transient"
    return "fatal"


class LiveLLMClient:
    def __init__(self, settings: Settings,
                 max_calls: int = MAX_LLM_CALLS_PER_RUN) -> None:
        self._settings = settings
        self._max_calls = max_calls
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    async def _call_once(self, *, model_id: str, messages: list[dict],
                         json_mode: bool, temperature: float):
        kwargs: dict = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "api_key": self._settings.groq_api_key,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return await acompletion(**kwargs)

    def _to_response(self, raw, model_id: str) -> LLMResponse:
        usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
        pt = int(usage.get("prompt_tokens", 0))
        ct = int(usage.get("completion_tokens", 0))
        self.prompt_tokens += pt
        self.completion_tokens += ct
        content = raw["choices"][0]["message"]["content"] or ""
        return LLMResponse(text=content, model=model_id,
                           prompt_tokens=pt, completion_tokens=ct)

    async def complete(self, *, model: str, messages: list[dict],
                       json_mode: bool = False,
                       temperature: float = 0.0) -> LLMResponse:
        """`model` is a ROLE name ('reasoning' | 'fast' | 'fallback'), not an ID.

        Retry/fallback policy, per tier in the role's chain:
          - quota error: advance to the next tier immediately, no sleep — a
            different model has an independent quota, so waiting buys nothing.
          - transient error (timeout/5xx/connection): one quick retry at the
            SAME tier after a short backoff, then advance if it fails again.
            This is not a quota signal, so a single ordinary network blip must
            not permanently downgrade the run's highest-value calls.
          - fatal error: advance immediately, no sleep. The chain is still
            worth trying (a different model may not share whatever tripped
            the error), but there is no signal here that waiting would help.
        The LAST tier has nowhere further to advance to, so it retries in
        place (the full backoff schedule) for both quota and transient errors
        before finally giving up. A fatal error never sleeps, on any tier.
        Exhausting the chain always raises — it never invents an answer.

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

            if is_last_tier:
                # Nowhere left to advance to: retry in place (quota and
                # transient alike) through the full backoff schedule; a
                # fatal error still breaks out without sleeping.
                for delay in (*_BACKOFF_S, None):
                    try:
                        raw = await self._call_once(
                            model_id=model_id, messages=messages,
                            json_mode=json_mode, temperature=temperature)
                    except Exception as err:                 # noqa: BLE001
                        last = err
                        if delay is None or _classify(err) == "fatal":
                            break
                        await asyncio.sleep(delay)
                        continue

                    self.calls += 1
                    return self._to_response(raw, model_id)
                continue  # exhausted the last tier; falls through to raise

            # Non-terminal tier: one attempt, then a policy-driven decision.
            try:
                raw = await self._call_once(
                    model_id=model_id, messages=messages,
                    json_mode=json_mode, temperature=temperature)
            except Exception as err:                         # noqa: BLE001
                last = err
                if _classify(err) == "transient":
                    await asyncio.sleep(_TRANSIENT_RETRY_S)
                    try:
                        raw = await self._call_once(
                            model_id=model_id, messages=messages,
                            json_mode=json_mode, temperature=temperature)
                    except Exception as err2:                # noqa: BLE001
                        last = err2
                        continue  # still failing after one retry: advance
                    self.calls += 1
                    return self._to_response(raw, model_id)
                continue  # quota or fatal: advance immediately, no sleep

            self.calls += 1
            return self._to_response(raw, model_id)

        raise RuntimeError(f"all models in chain for role '{role}' failed") from last
