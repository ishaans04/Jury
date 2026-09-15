"""Economics node. Task 5.3. PRD §16.5, §7.7.

Binds the best available parameter for each template variable and runs the
deterministic solver (`jury.engines.economics.solver.solve`). Every parameter
is tagged `evidence_backed` (with a `source_id`) or `founder_asserted` --
provenance is the join that lets `jury.graph.nodes.experiments.plan_experiments`
mechanically nominate the next experiment from sensitivity (PRD §16.6).

P8: no LLM call anywhere in this module -- economics is computed, not
described. `bind_parameters`/`run_economics` accept `transports` only to keep
this node's call shape identical to every other node's (the graph wiring in
`jury/graph/build.py` calls every node the same way); neither function ever
reaches into `transports.llm`.

Binding precedence per variable (brief, PRD §16.5): evidence whose scope
covers the founder's target scope, highest tier first (then highest
confidence as the tie-break within a tier); then a founder assertion; then
the template's own default. Refuting evidence is never bound -- "X is not
500" is not a measurement of X (P2) -- and evidence outside the target scope
is never bound either, or US-enterprise pricing would silently drive an
India-SMB model (PRD §12.1).

Unlike `reconcile`/`chair`, this node carries NO idempotency guard
(`jury.graph.idempotency.already_ran`): PRD §7.7 requires the model to be
"(re-)executed with the best available parameters AFTER cross-examination",
so a second call against the same run, once cross-examination has changed
the underlying evidence, is expected to produce a different, fresher result
-- guarding it would silently defeat the very re-run the PRD asks for.
"""
from dataclasses import dataclass

from jury.db.repositories import AssumptionRepo, EvidenceRepo, ModelRunRepo
from jury.engines.economics.solver import solve
from jury.engines.economics.templates import TEMPLATES
from jury.engines.scope import covers_target
from jury.graph.state import RunState
from jury.schemas.economics import Parameter
from jury.schemas.enums import Archetype, Provenance
from jury.schemas.scope import Scope
from jury.tracing.events import TraceSink
from jury.transport.protocols import Transports

NODE = "economics"

# spec §4 note: only four templates exist. ad_consumer and hardware are
# substituted onto the nearest-shaped template; the substitution is recorded
# in `model_runs.template_key` (never hidden) so it is visible to the founder
# and to anyone reading the ledger later.
ARCHETYPE_TEMPLATES: dict[Archetype, str] = {
    Archetype.MARKETPLACE: "marketplace_v1",
    Archetype.SUBSCRIPTION_SAAS: "saas_v1",
    Archetype.D2C: "d2c_v1",
    Archetype.SERVICES: "services_v1",
    Archetype.AD_CONSUMER: "saas_v1",
    Archetype.HARDWARE: "d2c_v1",
}

# Chair-side variable naming -> template parameter naming (brief, step 3).
# Only the names that actually differ need an entry; `_param_name` below
# tries the raw variable name against the template first, so an exact match
# (e.g. `take_rate`, `delivery_cost`) never needs to appear here at all.
VARIABLE_TO_PARAM: dict[str, str] = {
    "price_monthly": "price_monthly",
    "delivery_cost": "delivery_cost",
    "wtp_monthly": "price_monthly",
}


def _param_name(variable: str | None, template_params: set[str]) -> str | None:
    if variable is None:
        return None
    if variable in template_params:
        return variable
    mapped = VARIABLE_TO_PARAM.get(variable)
    if mapped in template_params:
        return mapped
    return None


@dataclass(slots=True)
class EconomicsRepos:
    """Every repository `run_economics` touches, bundled the way
    `jury.graph.nodes.cross_exam.CrossExamRepos` bundles a node's own repos."""
    evidence: EvidenceRepo
    assumption: AssumptionRepo
    model_run: ModelRunRepo


def _evidence_scope(row: dict) -> Scope:
    return Scope(geo=row["scope_geo"], segment=row["scope_segment"],
                tier=row["scope_tier"], period=row["scope_period"])


async def bind_parameters(state: RunState, *, repos: EconomicsRepos,
                          transports: Transports | None = None,
                          trace: TraceSink | None = None) -> dict[str, Parameter]:
    """Binds one `Parameter` (value + provenance + source_id) per template
    variable, for the template the run's archetype maps to.

    Every one of the template's parameters is present in the result -- a
    variable nothing bound to still gets an entry, at the template default,
    marked `founder_asserted` with no `source_id` (PRD §16.5: a default is a
    guess, which is exactly what makes it eligible to become an experiment
    later, PRD §16.6).
    """
    del transports, trace  # unused: P8, no LLM call and nothing to trace here
    run_id, project_id = state["run_id"], state["project_id"]
    archetype = Archetype(state["archetype"])
    template = TEMPLATES[ARCHETYPE_TEMPLATES[archetype]]
    target_scope = Scope(**state["target_scope"])
    template_params = set(template.params)

    evidence_rows = await repos.evidence.list_for_conflict_engine(project_id, run_id)
    assumption_rows = [a for a in await repos.assumption.list_for_project(project_id)
                       if str(a["run_id"]) == str(run_id)]

    # Qualifying evidence rows (supports, scope covers target), grouped by the
    # template parameter name they bind to.
    by_param: dict[str, list[dict]] = {}
    for row in evidence_rows:
        if row["direction"] != "supports":       # P2: refuting evidence is not a measurement
            continue
        if row["value_num"] is None:
            continue
        name = _param_name(row["variable"], template_params)
        if name is None:
            continue
        if not covers_target(_evidence_scope(row), target_scope):
            continue
        by_param.setdefault(name, []).append(row)

    # Founder assertions, grouped the same way. First one wins on a
    # collision -- a param asserted by more than one assumption is not
    # expected, and there is no principled way to prefer one over another.
    by_param_assertion: dict[str, dict] = {}
    for a in assumption_rows:
        if a["asserted_variable"] is None or a["asserted_value"] is None:
            continue
        name = _param_name(a["asserted_variable"], template_params)
        if name is None:
            continue
        by_param_assertion.setdefault(name, a)

    params: dict[str, Parameter] = {}
    for name, spec in template.params.items():
        rows = by_param.get(name)
        if rows:
            # Highest tier first (tier 1 is best -- TIER_WEIGHTS is
            # descending in tier number), then highest confidence.
            rows.sort(key=lambda r: (r["source_tier"], -float(r["confidence"])))
            winner = rows[0]
            params[name] = Parameter(
                value=float(winner["value_num"]), unit=spec.unit,
                provenance=Provenance.EVIDENCE_BACKED,
                source_id=str(winner["source_id"]),
                assumption_id=str(winner["assumption_id"]))
            continue

        asserted = by_param_assertion.get(name)
        if asserted is not None:
            params[name] = Parameter(
                value=float(asserted["asserted_value"]), unit=spec.unit,
                provenance=Provenance.FOUNDER_ASSERTED, source_id=None,
                assumption_id=str(asserted["id"]))
            continue

        params[name] = Parameter(
            value=spec.default, unit=spec.unit,
            provenance=Provenance.FOUNDER_ASSERTED, source_id=None,
            assumption_id=None)

    return params


async def run_economics(state: RunState, *, repos: EconomicsRepos,
                        transports: Transports | None = None,
                        trace: TraceSink | None = None) -> dict:
    """Returns a partial `RunState` update: `model_run`, `model_run_id`."""
    if trace is not None:
        await trace.emit(node=NODE, event="node_start")

    # Every template is keyed by archetype. A run whose detection dropped
    # (and whose founder never set one) has no template to solve -- degrade
    # to "no model" with a visible trace row rather than crashing the run
    # (PRD §18), so the jury can still rule on the evidence it has.
    try:
        archetype = Archetype(state.get("archetype"))
    except ValueError:
        if trace is not None:
            await trace.emit(node=NODE, event="error",
                             detail={"message": "no archetype set; economics model skipped"})
            await trace.emit(node=NODE, event="node_end")
        return {"model_run": None, "model_run_id": None}
    template_key = ARCHETYPE_TEMPLATES[archetype]

    params = await bind_parameters(state, repos=repos, transports=transports, trace=trace)
    result = solve(template_key, params)

    parameters_json = {k: v.model_dump(mode="json") for k, v in params.items()}
    outputs_json = result.outputs.model_dump(mode="json")
    breakpoints_json = [b.model_dump(mode="json") for b in result.breakpoints]
    sensitivity_json = [s.model_dump(mode="json") for s in result.sensitivity]

    model_run_id = await repos.model_run.create(
        project_id=state["project_id"], run_id=state["run_id"], template_key=template_key,
        parameters=parameters_json, outputs=outputs_json, breakpoints=breakpoints_json,
        sensitivity=sensitivity_json, viable=result.viable)

    model_run = {
        "id": model_run_id, "template_key": template_key,
        "parameters": parameters_json, "outputs": outputs_json,
        "breakpoints": breakpoints_json, "sensitivity": sensitivity_json,
        "viable": result.viable,
    }

    if trace is not None:
        await trace.emit(node=NODE, event="node_end")

    return {"model_run": model_run, "model_run_id": model_run_id}
