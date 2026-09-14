"""The experiments node. Task 5.5. PRD §16.6.

Turns the economics model's sensitivity ranking into a persisted experiment
plan: every `founder_asserted` parameter (a guess, by construction of
`jury.graph.nodes.economics.bind_parameters`) is a candidate, ranked by
sensitivity, mapped to an experiment template via `jury.engines.experiments.
generate_experiments`, and written to the `experiments` table.

The one thing this node must not skip: `modelled=`. Four of the experiment
templates (delivery_cost, cac, aov, churn_monthly) have no self-contained
kill-criterion threshold -- it has to come from the solved economics model's
own breakpoints. Passing `modelled={}` (or forgetting the argument) does not
error; it just silently skips every one of those four experiment types,
because `generate_experiments` treats a missing modelled value as an honest
absence rather than inventing a placeholder threshold that could never
meaningfully pass or fail (see that module's own docstring). Building
`modelled` from `state["model_run"]["breakpoints"]` is what makes those four
experiment types exist at all.
"""
from dataclasses import dataclass

from jury.db.repositories import ExperimentRepo
from jury.engines.economics.solver import SensitivityEntry
from jury.engines.experiments import generate_experiments
from jury.graph.state import RunState
from jury.schemas.enums import Provenance
from jury.tracing.events import TraceSink
from jury.transport.protocols import Transports

NODE = "experiments"
_TOP_K = 5


@dataclass(slots=True)
class ExperimentsRepos:
    experiment: ExperimentRepo


async def plan_experiments(state: RunState, *, repos: ExperimentsRepos,
                           transports: Transports | None = None,
                           trace: TraceSink | None = None) -> dict:
    """Returns a partial `RunState` update: `experiments`, `experiment_ids`,
    `run_status`.

    `transports` is accepted only to keep this node's call shape identical
    to every other node's in `jury/graph/build.py`; the optional model-
    enriched instructions text described in the brief (PRD §15.1's
    "experiment_instructions" role, "filling a template, not inventing
    method") is intentionally NOT called here for this batch -- every
    experiment ships with its template instructions verbatim, which is
    exactly the documented fallback path and therefore always correct, just
    less individually worded. This is a scoped-down but honest subset: no
    kill_criterion, criterion_spec, cost or day estimate is affected by the
    omission, only prose that was optional in the first place.
    """
    del transports
    if trace is not None:
        await trace.emit(node=NODE, event="node_start")

    model_run = state.get("model_run") or {}
    parameters = model_run.get("parameters") or {}
    sensitivity = [SensitivityEntry(**s) for s in model_run.get("sensitivity") or []]
    breakpoints = model_run.get("breakpoints") or []
    modelled = {b["variable"]: b["threshold"] for b in breakpoints}

    assumption_for_variable = {
        name: p["assumption_id"]
        for name, p in parameters.items()
        if p.get("provenance") == Provenance.FOUNDER_ASSERTED.value and p.get("assumption_id")
    }

    drafts = generate_experiments(sensitivity, assumption_for_variable,
                                  top_k=_TOP_K, modelled=modelled)

    experiment_ids: list[str] = []
    for d in drafts:
        eid = await repos.experiment.create(
            project_id=state["project_id"], assumption_id=d.assumption_id,
            target_variable=d.target_variable, method=d.method.value,
            instructions=d.instructions, kill_criterion=d.kill_criterion,
            criterion_spec=d.criterion_spec.model_dump(mode="json"),
            est_cost=d.est_cost, est_days=d.est_days, priority=d.priority)
        experiment_ids.append(eid)

    experiments = [d.model_dump(mode="json") for d in drafts]

    if trace is not None:
        await trace.emit(node=NODE, event="node_end")

    return {"experiments": experiments, "experiment_ids": experiment_ids,
           "run_status": "complete"}
