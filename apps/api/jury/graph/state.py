"""The run's shared state. Task 4.1.

A `TypedDict` rather than a pydantic model: the graph runs as a sequence of
nodes that each return only the keys they touch (`detect_archetype` returns
`archetype`/`archetype_confidence`/`target_scope`; `extract_assumptions`
returns `assumptions`), and the caller merges that partial dict into the
running state. A pydantic model's required-field validation would reject
every one of those partial updates; `total=False` is what makes a partial
update legal here.

Every top-level field this phase's boardroom needs is declared up front, even
though this task's two nodes populate only `archetype`, `archetype_confidence`,
`target_scope`, `assumptions` and `coverage_gaps` -- the remaining fields
(`evidence_ids`, `conflicts`, `cross_exam_done`, `model_run`, `verdict`,
`experiments`) belong to later Phase 4 tasks (chairs fan-out, conflict
engine, jury verdict) and are declared here so the state's shape is stable
across the whole phase rather than growing ad hoc per task.
Task 4.3 adds the fan-out fields. `evidence_ids`, `discovered` and
`partial_chairs` are written concurrently by five `Send`-dispatched chair
branches (`jury/graph/nodes/investigate.py`) that each return only their own
slice of these lists -- LangGraph merges concurrent branch outputs into the
shared state field by field, and its default merge for a plain `list`-typed
key is "last writer wins" (the state is simply overwritten), not concatenate.
Five branches racing to overwrite the same key would silently drop four
chairs' evidence, keeping only whichever branch happened to finish last --
exactly the "get it right here" bug the batch brief calls out explicitly.
`Annotated[list, operator.add]` installs `operator.add` (list
concatenation) as this field's reducer, so LangGraph adds each branch's
returned list onto the running total instead of replacing it.
"""
import operator
from typing import Annotated, Any, TypedDict


class RunState(TypedDict, total=False):
    # identity / input
    run_id: str
    project_id: str
    pitch: str
    artifacts: list[dict[str, Any]]

    # this task's outputs
    archetype: str | None
    archetype_confidence: float | None
    target_scope: dict[str, Any] | None
    assumptions: list[dict[str, Any]]
    coverage_gaps: list[dict[str, Any]]

    # Task 4.3: the hearing interrupt and five-way chair fan-out.
    # evidence_ids / discovered / partial_chairs are each written by up to
    # five concurrent `Send("chair", ...)` branches -- see the module
    # docstring for why the reducer must be additive.
    evidence_ids: Annotated[list[str], operator.add]
    discovered: Annotated[list[dict[str, Any]], operator.add]
    partial_chairs: Annotated[list[str], operator.add]
    conflicts: list[dict[str, Any]]
    coverage: dict[str, Any] | None
    run_status: str

    # later Phase 4/5 tasks
    cross_exam_done: bool
    model_run: dict[str, Any] | None
    verdict: dict[str, Any] | None
    experiments: list[dict[str, Any]]

    version: int
