"""The jury node. Task 5.4. PRD §9, §9.4, §9.5, §15.1.

The separation that matters (PRD §9.5): Evidence Confidence answers "how much
do we know?"; the verdict answers "what should you do?" They are deliberately
decoupled, and the order in this module is strict and load-bearing --

    load assumptions + evidence + conflicts
      -> evidence_confidence(...)          (jury.engines.scoring)
      -> apply_gate(...)                   (jury.engines.scoring)
      -> ONLY THEN ask the model for prose

The model never decides (PRD §15.1: "the score and verdict are computed in
code; the model only writes the explanation"). `RationaleResponse` carries
exactly one field -- `rationale: str` -- there is no field the model could
even attempt to put a decision into, and the computed `gate.decision` is
what gets persisted regardless of what the model's prose says. If the LLM is
unavailable (raises, or every repair stage drops), the verdict still exists
with a templated fallback rationale built straight from the gate result
(PRD §18: degrade to less prose, never to no decision).

A `HUNG_JURY` always ships with the three cheapest experiments that would
break the deadlock (PRD §9.4) -- `hung_jury_experiments` below, restricted to
blocking/high assumptions that are still open (no_evidence/uncertain),
ranked by sensitivity and then cut down to the 3 cheapest by (cost, days).
This is a *different* list from the general experiment plan
`jury.graph.nodes.experiments.plan_experiments` persists -- that one ranks
every founder_asserted parameter regardless of verdict; this one is a
verdict-attached subset shown immediately with the HUNG_JURY message, and is
never itself written to the `experiments` table.
"""
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from jury.db.repositories import AssumptionRepo, ConflictRepo, EvidenceRepo, VerdictRepo
from jury.engines.economics.solver import SensitivityEntry, find_viable_adjacent
from jury.engines.experiments import generate_experiments
from jury.engines.scoring import (
    AssumptionLike, EvidenceLike, apply_gate, assign_status, coverage as score_coverage,
    evidence_confidence,
)
from jury.graph.state import RunState
from jury.llm.models import TASK_ROLES
from jury.llm.structured import structured_report
from jury.schemas.economics import Parameter
from jury.schemas.enums import AssumptionStatus, Criticality, Decision, Direction
from jury.tracing.events import TraceSink
from jury.transport.protocols import Transports

NODE = "jury"
_ROLE = TASK_ROLES["jury_rationale"]

_CRITICAL = frozenset({Criticality.BLOCKING, Criticality.HIGH})
_OPEN_STATUSES = frozenset({AssumptionStatus.NO_EVIDENCE, AssumptionStatus.UNCERTAIN})
_FRICTION_SEVERITY = frozenset({"critical", "high"})


class RationaleResponse(BaseModel):
    """The model's only output: prose. There is no `decision` field to
    hijack -- structurally, the model cannot change the verdict."""
    model_config = ConfigDict(extra="forbid")
    rationale: str


@dataclass(slots=True)
class JuryRepos:
    """Every repository `rule` touches, plus the archetype's own checklist
    (`classes`) -- the hand-seeded external denominator `jury.engines.
    scoring.coverage` (P4) needs. `rule`'s brief signature carries no
    separate `classes` parameter, so it travels here instead, the same ad
    hoc bag `jury.graph.nodes.cross_exam.CrossExamRepos` already is; the
    caller (`jury/graph/build.py`) already has this exact list in hand from
    its own `build_graph(classes=...)` argument, the same one `coverage`/
    `reconcile` use."""
    assumption: AssumptionRepo
    evidence: EvidenceRepo
    conflict: ConflictRepo
    verdict: VerdictRepo
    classes: list[tuple[str, float, str]]


def _evidence_like(row: dict) -> EvidenceLike:
    return EvidenceLike(tier=row["source_tier"], confidence=float(row["confidence"]),
                        direction=Direction(row["direction"]), variable=row["variable"])


async def _load_run_data(state: RunState, repos: JuryRepos) -> tuple[
        list[AssumptionLike], dict[str, dict], list[dict]]:
    run_id, project_id = state["run_id"], state["project_id"]

    assumption_rows = [a for a in await repos.assumption.list_for_project(project_id)
                       if str(a["run_id"]) == str(run_id)]
    evidence_rows = await repos.evidence.list_for_conflict_engine(project_id, run_id)
    conflict_rows = [c for c in await repos.conflict.list_for_project(project_id)
                     if str(c["run_id"]) == str(run_id)]

    evidence_by_assumption: dict[str, list[dict]] = {}
    for row in evidence_rows:
        evidence_by_assumption.setdefault(str(row["assumption_id"]), []).append(row)

    unresolved_assumption_ids = {str(c["assumption_id"]) for c in conflict_rows
                                 if c["status"] == "open"}

    likes = [
        AssumptionLike(
            id=str(a["id"]), class_key=a["class_key"],
            criticality=Criticality(a["criticality"]),
            evidence=[_evidence_like(r) for r in evidence_by_assumption.get(str(a["id"]), [])],
            has_unresolved_conflict=str(a["id"]) in unresolved_assumption_ids)
        for a in assumption_rows
    ]
    assumption_by_id = {str(a["id"]): a for a in assumption_rows}
    return likes, assumption_by_id, conflict_rows


def build_friction(conflicts: list[dict], deltas: list[dict]) -> list[dict]:
    """Names the conflicts that mattered (PRD §7.8): every conflict at
    critical/high severity, each with its kind/rule/status and, where a
    cross-examination round actually moved a position on it, the reason it
    resolved or was conceded. A sub-critical (medium/low) chair disagreement
    is noise, not friction -- it is deliberately excluded.
    """
    deltas_by_conflict: dict[str, list[dict]] = {}
    for d in deltas:
        deltas_by_conflict.setdefault(str(d.get("conflict_id")), []).append(d)

    friction: list[dict] = []
    for c in conflicts:
        if c.get("severity") not in _FRICTION_SEVERITY:
            continue
        item = {"kind": c["kind"], "rule": c["rule"], "status": c["status"]}
        cid = str(c.get("id"))
        cds = deltas_by_conflict.get(cid)
        if cds:
            item["resolution"] = cds[-1].get("reason")
        friction.append(item)
    return friction


async def hung_jury_experiments(state: RunState, *, repos: JuryRepos) -> list:
    """The three cheapest experiments that would break the deadlock (PRD
    §9.4): sensitivity-ranked, founder_asserted parameters bound to a
    blocking/high assumption that is still open, cut to the 3 cheapest by
    (est_cost, est_days). Returns `ExperimentDraft`s -- never persisted here,
    see the module docstring for why."""
    model_run = state.get("model_run") or {}
    sensitivity = [SensitivityEntry(**s) for s in model_run.get("sensitivity") or []]
    parameters = model_run.get("parameters") or {}
    breakpoints = model_run.get("breakpoints") or []
    modelled = {b["variable"]: b["threshold"] for b in breakpoints}

    _, assumption_by_id, conflict_rows = await _load_run_data(state, repos)
    unresolved_ids = {str(c["assumption_id"]) for c in conflict_rows if c["status"] == "open"}

    evidence_rows = await repos.evidence.list_for_conflict_engine(
        state["project_id"], state["run_id"])
    evidence_by_assumption: dict[str, list[dict]] = {}
    for row in evidence_rows:
        evidence_by_assumption.setdefault(str(row["assumption_id"]), []).append(row)

    def _is_blocking_open(assumption_id: str) -> bool:
        a = assumption_by_id.get(assumption_id)
        if a is None or Criticality(a["criticality"]) not in _CRITICAL:
            return False
        evid = [_evidence_like(r) for r in evidence_by_assumption.get(assumption_id, [])]
        status = assign_status(evid, assumption_id in unresolved_ids)
        return status in _OPEN_STATUSES

    assumption_for_variable = {
        name: p["assumption_id"]
        for name, p in parameters.items()
        if p.get("assumption_id") and _is_blocking_open(p["assumption_id"])
    }

    drafts = generate_experiments(sensitivity, assumption_for_variable,
                                  top_k=max(len(sensitivity), 1), modelled=modelled)
    drafts.sort(key=lambda d: (d.est_cost if d.est_cost is not None else 0.0,
                               d.est_days if d.est_days is not None else 0))
    return drafts[:3]


def _fallback_rationale(gate, confidence: float, components) -> str:
    gate_line = (f"Gate condition fired: {gate.gate_triggered}."
                if gate.gate_triggered else "No gate condition fired.")
    return (f"{gate.decision.value}. Evidence Confidence {confidence:.1f}/100 "
           f"(coverage {components.coverage:.2f}, mean strength "
           f"{components.mean_strength:.2f}, contradiction "
           f"{components.contradiction:.2f}, open critical "
           f"{components.open_critical:.2f}). {gate_line}")


async def _rationale(gate, confidence: float, components, friction: list[dict], *,
                     transports: Transports, trace: TraceSink | None) -> str:
    """Asks the model for prose ONLY -- the decision, confidence and gate are
    already final by the time this runs. The model is handed the computed
    decision as a fact to explain, told the decision is final, and its
    response schema (`RationaleResponse`) has no field it could use to
    change it even if it tried (PRD §15.1)."""
    facts = (
        f"Computed decision (already final -- do not restate or contradict it, "
        f"explain it): {gate.decision.value}\n"
        f"Evidence Confidence: {confidence:.1f}/100\n"
        f"Components -- coverage: {components.coverage:.2f}, "
        f"mean_strength: {components.mean_strength:.2f}, "
        f"contradiction: {components.contradiction:.2f}, "
        f"open_critical: {components.open_critical:.2f}\n"
        f"Gate condition fired: {gate.gate_triggered or 'none'}\n"
        f"Friction (conflicts that mattered): {friction}\n"
    )
    prompt = (
        "Write a short, factual rationale (2-4 sentences) explaining a "
        "startup evaluation verdict that has already been computed in code. "
        "Cite the record below. Do not offer independent advice, do not "
        "second-guess the decision, and do not use first-person opinion "
        f"phrasing. The decision is final: {gate.decision.value}.\n\n{facts}\n"
        "Return only the rationale prose."
    )
    try:
        report = await structured_report(transports.llm, role=_ROLE, prompt=prompt,
                                         schema=RationaleResponse, trace=trace)
        value = report.value
    except Exception as err:      # noqa: BLE001 - PRD §18: degrade, never lose the verdict
        if trace is not None:
            await trace.emit(node=NODE, event="error",
                             detail={"error": f"{type(err).__name__}: {err}"})
        value = None

    if value is not None and value.rationale.strip():
        return value.rationale
    return _fallback_rationale(gate, confidence, components)


async def rule(state: RunState, *, repos: JuryRepos, transports: Transports,
               trace: TraceSink | None = None) -> dict:
    """Returns a partial `RunState` update: `verdict`, `verdict_id`,
    `hung_jury_experiments`."""
    if trace is not None:
        await trace.emit(node=NODE, event="node_start")

    assumption_likes, _, conflict_rows = await _load_run_data(state, repos)
    class_pairs = [(key, weight) for key, weight, _question in repos.classes]

    open_conflicts = [c for c in conflict_rows if c["status"] == "open"]
    unresolved_conflicts = len(open_conflicts)

    confidence, components = evidence_confidence(
        class_pairs, assumption_likes, unresolved_conflicts)

    critical_ids = {a.id for a in assumption_likes if a.criticality in _CRITICAL}
    unresolved_critical = sum(1 for c in open_conflicts
                              if str(c["assumption_id"]) in critical_ids)

    coverage_score = score_coverage(class_pairs, assumption_likes)
    model_run = state.get("model_run") or {}
    economics_viable = bool(model_run.get("viable", False))
    # PRD §9.4: is there a viable configuration reachable by changing only
    # the founder's still-guessed parameters, holding evidence-backed ones
    # fixed? Pure computation over the persisted model run -- no new LLM
    # call. A run that never reached economics (no model_run) has nothing to
    # search over, so it stays conservatively False, same as before.
    has_viable_adjacent = False
    if model_run.get("template_key") and model_run.get("parameters"):
        parameters = {name: Parameter(**p) for name, p in model_run["parameters"].items()}
        has_viable_adjacent = find_viable_adjacent(model_run["template_key"], parameters)

    gate = apply_gate(coverage_score, assumption_likes, confidence,
                      has_viable_adjacent, economics_viable, unresolved_critical)

    friction_conflicts = [
        {"id": c.get("id"), "kind": c["kind"], "rule": c["rule"],
         "severity": c["severity"], "status": c["status"]}
        for c in (state.get("conflicts") or [])
    ]
    conflict_ids = [c["id"] for c in friction_conflicts if c.get("id")]
    deltas = await repos.conflict.list_deltas(conflict_ids)
    friction = build_friction(friction_conflicts, deltas)

    hung_experiments: list[dict] = []
    if gate.decision is Decision.HUNG_JURY:
        drafts = await hung_jury_experiments(state, repos=repos)
        hung_experiments = [d.model_dump(mode="json") for d in drafts]

    rationale = await _rationale(gate, confidence, components, friction,
                                 transports=transports, trace=trace)

    components_json = components.model_dump(mode="json")
    verdict_id = await repos.verdict.create(
        run_id=state["run_id"], project_id=state["project_id"],
        decision=gate.decision.value, evidence_confidence=confidence,
        components=components_json, gate_triggered=gate.gate_triggered,
        friction=friction, rationale=rationale)

    verdict = {
        "decision": gate.decision.value, "evidence_confidence": confidence,
        "components": components_json, "gate_triggered": gate.gate_triggered,
        "friction": friction, "rationale": rationale,
    }

    if trace is not None:
        await trace.emit(node=NODE, event="node_end")

    return {"verdict": verdict, "verdict_id": verdict_id,
           "hung_jury_experiments": hung_experiments}
