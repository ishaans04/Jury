"""Reconciliation. Task 4.3. PRD §7.5, §16.3.

Runs strictly after the five-way chair fan-out joins back together.
Deterministic only: dedup already happened at write time (P10, `EvidenceRepo.
insert_verified`'s `dedup_hash` unique constraint), so this node's own job is
running `jury.engines.conflict.detect_conflicts` (R1-R5, pure functions, no
LLM anywhere) over the run's assumptions/evidence, persisting whatever it
finds, and scoring coverage now that investigation has actually happened --
never before it (PRD §7.3: "Coverage is scored after investigation, not
before" -- `coverage_gaps`, computed pre-hearing, is a silence report; the
`coverage` score computed here is post-investigation and answers a different
question: how much of the checklist now carries evidence).
"""
from jury.db.repositories import AssumptionRepo, ConflictRepo, EvidenceRepo
from jury.engines.conflict import (
    AssumptionForConflict, ConflictInput, EvidenceForConflict, detect_conflicts,
)
from jury.engines.scoring import AssumptionLike, EvidenceLike, coverage as score_coverage
from jury.graph.idempotency import already_ran
from jury.graph.state import RunState
from jury.schemas.enums import Chair, Criticality, Direction, Origin
from jury.schemas.scope import Scope
from jury.tracing.events import TraceSink
from jury.transport.protocols import Transports

NODE = "reconcile"

# Mirrors jury.engines.conflict.DetectedConflict.triggers_cross_exam exactly
# (R3 always; R1/R2 only at critical/high severity, i.e. a blocking/high
# assumption -- _SEVERITY maps Criticality -> severity one-for-one; R4/R5
# never). Not persisted in the `conflicts` table (no such column) -- it is a
# pure function of kind+severity, computed fresh whenever `conflicts` is
# threaded into RunState, exactly like it was computed once, in memory,
# right after detection.
_CROSS_EXAM_SEVERITY = frozenset({"critical", "high"})


def _triggers_cross_exam(kind: str, severity: str) -> bool:
    if kind == "founder_vs_world":
        return True
    if kind == "chair_vs_chair":
        return severity in _CROSS_EXAM_SEVERITY
    return False


def _scope_of(row: dict) -> Scope:
    return Scope(geo=row["scope_geo"], segment=row["scope_segment"],
                tier=row["scope_tier"], period=row["scope_period"])


def _evidence_for_conflict(row: dict) -> EvidenceForConflict:
    return EvidenceForConflict(
        id=str(row["id"]), chair=Chair(row["chair"]), direction=Direction(row["direction"]),
        variable=row["variable"],
        value_num=float(row["value_num"]) if row["value_num"] is not None else None,
        value_min=float(row["value_min"]) if row["value_min"] is not None else None,
        value_max=float(row["value_max"]) if row["value_max"] is not None else None,
        tier=row["source_tier"], scope=_scope_of(row))


def _evidence_like(row: dict) -> EvidenceLike:
    return EvidenceLike(tier=row["source_tier"], confidence=float(row["confidence"]),
                        direction=Direction(row["direction"]), variable=row["variable"])


async def run_reconcile(state: RunState, *, pool, transports: Transports,
                        classes: list[tuple[str, float, str]],
                        trace: TraceSink | None = None) -> dict:
    run_id, project_id = state["run_id"], state["project_id"]

    if trace is not None:
        await trace.emit(node=NODE, event="node_start")

    assumption_repo, evidence_repo, conflict_repo = (
        AssumptionRepo(pool), EvidenceRepo(pool), ConflictRepo(pool))

    assumption_rows = [a for a in await assumption_repo.list_for_project(project_id)
                       if str(a["run_id"]) == str(run_id)]
    evidence_rows = await evidence_repo.list_for_conflict_engine(project_id, run_id)

    evidence_by_assumption: dict[str, list[dict]] = {}
    for row in evidence_rows:
        evidence_by_assumption.setdefault(str(row["assumption_id"]), []).append(row)

    if not await already_ran(transports.kv, run_id, NODE):
        inputs = []
        for a in assumption_rows:
            rows = evidence_by_assumption.get(str(a["id"]), [])
            inputs.append(ConflictInput(
                assumption=AssumptionForConflict(
                    id=str(a["id"]), origin=Origin(a["origin"]),
                    criticality=Criticality(a["criticality"]),
                    asserted_variable=a["asserted_variable"],
                    asserted_value=(float(a["asserted_value"])
                                   if a["asserted_value"] is not None else None)),
                target_scope=Scope(**state["target_scope"]),
                evidence=[_evidence_for_conflict(r) for r in rows]))

        detected = detect_conflicts(inputs)
        for d in detected:
            await conflict_repo.create(
                project_id=project_id, run_id=run_id, assumption_id=d.assumption_id,
                kind=d.kind.value, left_ref=d.left_ref, right_ref=d.right_ref,
                rule=d.rule.value, severity=d.severity)

    conflict_rows = [c for c in await conflict_repo.list_for_project(project_id)
                     if str(c["run_id"]) == str(run_id)]

    assumption_likes = [
        AssumptionLike(id=str(a["id"]), class_key=a["class_key"],
                      criticality=Criticality(a["criticality"]),
                      evidence=[_evidence_like(r)
                               for r in evidence_by_assumption.get(str(a["id"]), [])])
        for a in assumption_rows
    ]
    class_pairs = [(key, weight) for key, weight, _question in classes]
    score = score_coverage(class_pairs, assumption_likes)

    run_status = "partial" if state.get("partial_chairs") else "ok"

    if trace is not None:
        await trace.emit(node=NODE, event="node_end")

    return {
        "conflicts": [{"id": str(c["id"]), "rule": c["rule"], "kind": c["kind"],
                      "severity": c["severity"], "status": c["status"],
                      "triggers_cross_exam": _triggers_cross_exam(c["kind"], c["severity"])}
                     for c in conflict_rows],
        "coverage": {"score": score},
        "run_status": run_status,
    }
