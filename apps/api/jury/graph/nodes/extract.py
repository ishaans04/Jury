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

    Two normalisations run on every surviving draft, both defence in depth
    against a model that ignores its own prompt rather than trusting it:

    - `class_key` is checked against `classes` (the same checklist embedded
      in the prompt). A key the model invents cannot manufacture a false
      "covered" class in `coverage_gaps` -- that function only ever iterates
      the supplied list -- but an unresolvable key could still land in the
      ledger as a foreign key into `assumption_classes` that does not
      resolve. An invented key is dropped to `None` rather than rejecting
      the whole assumption: the assumption itself may still be real and
      worth keeping, it is simply uncounted for coverage purposes. A trace
      row is emitted so this correction is visible, not silent.
    - `origin` is clamped to `Origin.FOUNDER` unconditionally, and
      `discovered_by` cleared alongside it. Extraction runs before any chair
      has investigated anything, so there is no legitimate way for a
      "discovered" assumption to originate here -- letting one through would
      misattribute a founder belief to a chair that never looked at it,
      undermining the founder-vs-investigation distinction the whole
      product is built on.
    """
    prompt = assumption_extraction_prompt(state["pitch"], classes)
    report = await structured_report(
        transports.llm, role=_ROLE, prompt=prompt, schema=ExtractionResult, trace=trace)
    result = report.value
    if result is None:
        return {"assumptions": []}

    known_keys = {key for key, _weight, _question in classes}

    drafts: list[dict] = []
    for draft in result.assumptions:
        updates: dict = {}

        if draft.class_key is not None and draft.class_key not in known_keys:
            updates["class_key"] = None
            if trace is not None:
                await trace.emit(
                    node="extract", event="error",
                    detail={"reason": "class_key not in checklist; dropped to null",
                            "invented_class_key": draft.class_key,
                            "statement": draft.statement})

        # This pipeline only ever emits founder-origin assumptions (see the
        # docstring above) -- clamp both fields together, unconditionally,
        # regardless of what the model actually returned.
        if draft.origin != Origin.FOUNDER or draft.discovered_by is not None:
            updates["origin"] = Origin.FOUNDER
            updates["discovered_by"] = None

        if updates:
            draft = draft.model_copy(update=updates)
        drafts.append(draft.model_dump(mode="json"))

    return {"assumptions": drafts}
