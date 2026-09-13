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
"""
from typing import Any, TypedDict


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

    # later Phase 4 tasks
    evidence_ids: list[str]
    conflicts: list[dict[str, Any]]
    cross_exam_done: bool
    model_run: dict[str, Any] | None
    verdict: dict[str, Any] | None
    experiments: list[dict[str, Any]]

    version: int
