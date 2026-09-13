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
