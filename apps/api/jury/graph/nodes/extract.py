"""Assumption extraction node. Task 4.1. F5, PRD §7.3.

Extracts the founder's falsifiable assumptions from the pitch, classified
against the archetype's real belief-class checklist (never a model-invented
one -- see `jury.llm.prompts` for why that boundary matters) and scored on
all three axes the boardroom later argues about.
"""
from pydantic import BaseModel, ConfigDict

from jury.graph.state import RunState
from jury.llm.models import TASK_ROLES
from jury.llm.prompts import assumption_extraction_prompt
from jury.llm.structured import structured_report
from jury.schemas.assumption import AssumptionDraft
from jury.schemas.enums import Origin
from jury.tracing.events import TraceSink
from jury.transport.protocols import Transports

_ROLE = TASK_ROLES["assumption_extraction"]


class ExtractionResult(BaseModel):
    """Output contract for the extraction call: a flat list of drafts."""
    model_config = ConfigDict(extra="forbid")
    assumptions: list[AssumptionDraft]


async def extract_assumptions(state: RunState, *, transports: Transports,
                              classes: list[tuple[str, float, str]],
                              trace: TraceSink | None = None) -> dict:
    """Returns a partial `RunState` update: `assumptions`.

    `classes` is the archetype's checklist as `(key, crit_weight, question)`
    tuples straight from the `assumption_classes` table (P4) -- passed
    through to the prompt as data, never generated here or by the model.

    A dropped extraction (the repair loop exhausts every stage) returns an
    empty list, never a partially-built row: `structured_report` only ever
    hands back a fully-validated `ExtractionResult` or `None`, so there is no
    code path here that could assemble a malformed assumption from pieces.
    """
    prompt = assumption_extraction_prompt(state["pitch"], classes)
    report = await structured_report(
        transports.llm, role=_ROLE, prompt=prompt, schema=ExtractionResult, trace=trace)
    result = report.value
    if result is None:
        return {"assumptions": []}

    drafts: list[dict] = []
    for draft in result.assumptions:
        # Defence in depth alongside the database CHECK constraint
        # (`origin='founder'` implies `discovered_by is null`): this
        # pipeline only ever emits founder-origin assumptions, so
        # discovered_by is forced null regardless of what the model
        # returned, rather than trusting it to have obeyed the prompt.
        if draft.origin == Origin.FOUNDER and draft.discovered_by is not None:
            draft = draft.model_copy(update={"discovered_by": None})
        drafts.append(draft.model_dump(mode="json"))

    return {"assumptions": drafts}
