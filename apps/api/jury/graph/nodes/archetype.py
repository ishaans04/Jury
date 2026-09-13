"""Archetype detection node. Task 4.1. PRD §12.3, spec §26.2.

Classifies the pitch into one of the six archetypes seeded in
`assumption_classes` and infers a default target scope for the intake form.
Uses `structured_report` (the five-stage repair loop) exclusively -- no
hand-rolled JSON parsing here, matching every other structured LLM call in
the codebase (jury.chairs.base, jury.llm.structured).
"""
from pydantic import BaseModel, ConfigDict, Field

from jury.graph.state import RunState
from jury.llm.models import TASK_ROLES
from jury.llm.prompts import archetype_detection_prompt
from jury.llm.structured import structured_report
from jury.schemas.enums import Archetype
from jury.schemas.scope import Scope
from jury.tracing.events import TraceSink
from jury.transport.protocols import Transports

_ROLE = TASK_ROLES["archetype_detection"]


class ArchetypeResult(BaseModel):
    """Output contract for the archetype-detection call."""
    model_config = ConfigDict(extra="forbid")
    archetype: Archetype
    confidence: float = Field(ge=0.0, le=1.0)
    inferred_scope: Scope
    reasoning: str


async def detect_archetype(state: RunState, *, transports: Transports,
                           trace: TraceSink | None = None) -> dict:
    """Returns a partial `RunState` update: `archetype`, `archetype_confidence`,
    `target_scope`.

    A dropped detection (the repair loop exhausts every stage, PRD §15.3
    mitigation 5) must not crash the graph -- it degrades to an unset
    archetype and a zero confidence, and the founder still has the explicit
    intake form (spec §26.2) as the path to a correct scope by hand.
    """
    prompt = archetype_detection_prompt(state["pitch"])
    report = await structured_report(
        transports.llm, role=_ROLE, prompt=prompt, schema=ArchetypeResult, trace=trace)
    result = report.value
    if result is None:
        return {"archetype": None, "archetype_confidence": 0.0, "target_scope": None}

    return {
        "archetype": result.archetype.value,
        "archetype_confidence": result.confidence,
        "target_scope": result.inferred_scope.model_dump(mode="json"),
    }
