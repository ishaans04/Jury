"""Affected-only re-run. Task 6.4. PRD §7.10, spec §26.5.

`jury.api.routers.experiments.log_result` is the caller: once a logged
result has mechanically flipped one assumption's status
(`jury.engines.criterion.status_for_result` -- no model consulted),
`rerun_affected` decides, via `jury.engines.affected.affected_closure`, what
downstream state that one change actually touches, and re-runs only that:

  - economics (`jury.graph.nodes.economics.run_economics`), only if a
    parameter is bound to the changed assumption -- reusing the exact same
    node function the initial pipeline runs, never a re-implementation of
    the binding/solve logic;
  - the jury verdict (`jury.graph.nodes.jury.rule`), always, since
    Evidence Confidence is a function of every assumption's status.

Deliberately NOT re-run: `investigate`/chairs, cross-exam, archetype
detection. Nothing here calls `transports.search` or `transports.fetch`,
and the only `transports.llm` call anywhere in this module is the single
rationale-prose call already inside `jury.graph.nodes.jury.rule` (P8/PRD
§15.1: the model writes prose, never the decision) -- that is spec §26.5's
"affected-only" made literal: zero new searches, at most one LLM call.

`run_id` here is the run the changed assumption (and its evidence) was
originally created under, NOT a new run row -- `jury.graph.nodes.economics.
bind_parameters` and `jury.graph.nodes.jury.rule`'s own `_load_run_data`
both scope their reads to one `run_id`, so re-using the founding run's id is
what lets this re-run see the SAME assumptions/evidence the original run
saw (plus whatever the caller inserted for the logged result) while still
writing its own fresh `model_runs`/`verdicts` rows against that id --
`jury.db.snapshot.build_snapshot(pool, project_id, run_id)` then picks up
exactly those fresh rows (it takes the latest-by-`created_at` row for that
`run_id`, not the first).
"""
from jury.db.repositories import AssumptionRepo, ConflictRepo, EvidenceRepo, ModelRunRepo, VerdictRepo
from jury.engines.affected import affected_closure
from jury.graph.nodes.economics import EconomicsRepos, run_economics
from jury.graph.nodes.jury import JuryRepos, rule
from jury.graph.state import RunState
from jury.tracing.events import TraceSink
from jury.transport.protocols import Transports


async def _latest_model_run(pool, project_id: str, run_id: str) -> dict | None:
    rows = [r for r in await ModelRunRepo(pool).list_for_project(project_id)
           if str(r["run_id"]) == str(run_id)]
    return rows[-1] if rows else None


async def rerun_affected(project_id: str, run_id: str, changed_assumption_id: str, *,
                         pool, transports: Transports, archetype: str, target_scope: dict,
                         classes: list[tuple[str, float, str]],
                         trace: TraceSink | None = None) -> RunState:
    """Returns the resulting `RunState`, with `model_run`/`verdict` set to
    whatever this call actually recomputed (carried forward, untouched, from
    the latest existing row when the closure says a piece did not need to
    move)."""
    latest_model_run = await _latest_model_run(pool, project_id, run_id)
    parameters = (latest_model_run["parameters"] if latest_model_run else {}) or {}
    sensitivity = (latest_model_run["sensitivity"] if latest_model_run else []) or []

    parameter_bindings = {
        name: str(p["assumption_id"])
        for name, p in parameters.items() if p.get("assumption_id")
    }

    closure = affected_closure(changed_assumption_id,
                               parameter_bindings=parameter_bindings,
                               sensitivity=sensitivity)

    state: RunState = {
        "run_id": run_id, "project_id": project_id, "archetype": archetype,
        "target_scope": target_scope, "conflicts": [],
    }

    if closure.recompute_economics:
        econ_repos = EconomicsRepos(evidence=EvidenceRepo(pool),
                                    assumption=AssumptionRepo(pool),
                                    model_run=ModelRunRepo(pool))
        econ_out = await run_economics(state, repos=econ_repos, transports=transports,
                                       trace=trace)
        state = {**state, **econ_out}
    elif latest_model_run is not None:
        # Nothing bound to the changed assumption moved -- carry the run's
        # existing model_run forward untouched (no new model_runs row) so
        # `rule` below still has real economics viability to gate against.
        state = {**state, "model_run": {
            "id": str(latest_model_run["id"]), "template_key": latest_model_run["template_key"],
            "parameters": parameters, "outputs": latest_model_run["outputs"],
            "breakpoints": latest_model_run["breakpoints"], "sensitivity": sensitivity,
            "viable": latest_model_run["viable"],
        }}

    if closure.recompute_verdict:
        jury_repos = JuryRepos(assumption=AssumptionRepo(pool), evidence=EvidenceRepo(pool),
                               conflict=ConflictRepo(pool), verdict=VerdictRepo(pool),
                               classes=classes)
        jury_out = await rule(state, repos=jury_repos, transports=transports, trace=trace)
        state = {**state, **jury_out}

    return state
