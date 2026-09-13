"""Conflict detection. PRD §16.3. Deterministic — no LLM anywhere in this module.

R3 is the rule that earns the product its existence: the founder's pitch is a
set of claims in the same system as everything else, and it is expected to lose.
"""
from dataclasses import dataclass, field
from itertools import combinations

from jury.engines.scope import covers_target, scopes_overlap
from jury.schemas.enums import (
    Chair, ConflictKind, ConflictRule, Criticality, Direction, Origin,
)
from jury.schemas.scope import Scope

VALUE_TOLERANCE = 0.10        # R2 band
FOUNDER_DIVERGENCE = 0.25     # R3 threshold
_CROSS_EXAM_CRITICALITY = frozenset({Criticality.BLOCKING, Criticality.HIGH})
_R4_CRITICALITY = frozenset({Criticality.BLOCKING, Criticality.HIGH, Criticality.MEDIUM})
_SEVERITY = {Criticality.BLOCKING: "critical", Criticality.HIGH: "high",
             Criticality.MEDIUM: "medium", Criticality.LOW: "low"}


@dataclass(frozen=True, slots=True)
class EvidenceForConflict:
    id: str
    chair: Chair
    direction: Direction
    variable: str | None
    value_num: float | None
    value_min: float | None
    value_max: float | None
    tier: int
    scope: Scope


@dataclass(frozen=True, slots=True)
class AssumptionForConflict:
    id: str
    origin: Origin
    criticality: Criticality
    asserted_variable: str | None = None
    asserted_value: float | None = None


@dataclass(frozen=True, slots=True)
class ConflictInput:
    assumption: AssumptionForConflict
    target_scope: Scope
    evidence: list[EvidenceForConflict] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DetectedConflict:
    assumption_id: str
    kind: ConflictKind
    rule: ConflictRule
    left_ref: dict
    right_ref: dict | None
    severity: str
    triggers_cross_exam: bool


def _interval(e: EvidenceForConflict) -> tuple[float, float] | None:
    """Collapse an item to a numeric interval, or None if it carries no number."""
    if e.value_min is not None and e.value_max is not None:
        return (e.value_min, e.value_max)
    if e.value_num is not None:
        return (e.value_num, e.value_num)
    return None


def _diverges(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """True if the two intervals are disjoint beyond the +/-10% tolerance band."""
    lo_a, hi_a = a
    lo_b, hi_b = b
    if lo_a <= hi_b and lo_b <= hi_a:       # overlapping intervals never conflict
        return False
    gap_low, gap_high = (hi_a, lo_b) if hi_a < lo_b else (hi_b, lo_a)
    anchor = abs(gap_low) or abs(gap_high)
    if anchor == 0:
        return gap_high != gap_low
    return (gap_high - gap_low) / anchor > VALUE_TOLERANCE


def _r1(inp: ConflictInput) -> list[DetectedConflict]:
    """Opposing directions, both tier <= 2, overlapping scope."""
    out: list[DetectedConflict] = []
    supports = [e for e in inp.evidence
                if e.direction is Direction.SUPPORTS and e.tier <= 2]
    refutes = [e for e in inp.evidence
               if e.direction is Direction.REFUTES and e.tier <= 2]
    for s in supports:
        for r in refutes:
            if not scopes_overlap(s.scope, r.scope):
                continue
            out.append(DetectedConflict(
                assumption_id=inp.assumption.id,
                kind=ConflictKind.CHAIR_VS_CHAIR,
                rule=ConflictRule.R1,
                left_ref={"type": "evidence", "id": s.id},
                right_ref={"type": "evidence", "id": r.id},
                severity=_SEVERITY[inp.assumption.criticality],
                triggers_cross_exam=(
                    inp.assumption.criticality in _CROSS_EXAM_CRITICALITY),
            ))
    return out


def _r2(inp: ConflictInput) -> list[DetectedConflict]:
    """Same variable, overlapping scope, numerically divergent beyond the band."""
    out: list[DetectedConflict] = []
    numeric = [e for e in inp.evidence if e.variable and _interval(e) is not None]
    for a, b in combinations(numeric, 2):
        if a.variable != b.variable:
            continue
        if not scopes_overlap(a.scope, b.scope):
            continue
        if not _diverges(_interval(a), _interval(b)):
            continue
        out.append(DetectedConflict(
            assumption_id=inp.assumption.id,
            kind=ConflictKind.CHAIR_VS_CHAIR,
            rule=ConflictRule.R2,
            left_ref={"type": "evidence", "id": a.id},
            right_ref={"type": "evidence", "id": b.id},
            severity=_SEVERITY[inp.assumption.criticality],
            triggers_cross_exam=(
                inp.assumption.criticality in _CROSS_EXAM_CRITICALITY),
        ))
    return out


def _r3(inp: ConflictInput) -> list[DetectedConflict]:
    """Founder vs world. abs(V - E) / E > 0.25. Always triggers cross-examination."""
    asm = inp.assumption
    if asm.origin is not Origin.FOUNDER:
        return []
    if asm.asserted_variable is None or asm.asserted_value is None:
        return []

    out: list[DetectedConflict] = []
    for e in inp.evidence:
        if e.variable != asm.asserted_variable or e.value_num is None:
            continue
        if not scopes_overlap(e.scope, inp.target_scope):
            continue
        if e.value_num == 0:
            diverges = asm.asserted_value != 0
        else:
            diverges = (abs(asm.asserted_value - e.value_num) / abs(e.value_num)
                        > FOUNDER_DIVERGENCE)
        if not diverges:
            continue
        out.append(DetectedConflict(
            assumption_id=asm.id,
            kind=ConflictKind.FOUNDER_VS_WORLD,
            rule=ConflictRule.R3,
            left_ref={"type": "assumption", "id": asm.id},
            right_ref={"type": "evidence", "id": e.id},
            severity=_SEVERITY[asm.criticality],
            triggers_cross_exam=True,      # PRD §16.3: R3 ALWAYS
        ))
    return out


def _r4(inp: ConflictInput) -> list[DetectedConflict]:
    """Critical assumption with zero evidence. Silence is a finding."""
    if inp.evidence or inp.assumption.criticality not in _R4_CRITICALITY:
        return []
    return [DetectedConflict(
        assumption_id=inp.assumption.id,
        kind=ConflictKind.NO_EVIDENCE,
        rule=ConflictRule.R4,
        left_ref={"type": "assumption", "id": inp.assumption.id},
        right_ref=None,
        severity=_SEVERITY[inp.assumption.criticality],
        triggers_cross_exam=False,     # reported, and it feeds the gate
    )]


def _r5(inp: ConflictInput) -> list[DetectedConflict]:
    """Evidence exists but none of it covers the founder's target scope."""
    if not inp.evidence:
        return []
    if any(covers_target(e.scope, inp.target_scope) for e in inp.evidence):
        return []
    return [DetectedConflict(
        assumption_id=inp.assumption.id,
        kind=ConflictKind.SCOPE_GAP,
        rule=ConflictRule.R5,
        left_ref={"type": "assumption", "id": inp.assumption.id},
        right_ref={"type": "evidence", "id": inp.evidence[0].id},
        severity=_SEVERITY[inp.assumption.criticality],
        triggers_cross_exam=False,     # a gap, not a contradiction (F9)
    )]


def detect_conflicts(inputs: list[ConflictInput]) -> list[DetectedConflict]:
    """Run R1-R5 over every assumption. Order is stable: input order, then R1..R5."""
    out: list[DetectedConflict] = []
    for inp in inputs:
        out.extend(_r1(inp))
        out.extend(_r2(inp))
        out.extend(_r3(inp))
        out.extend(_r4(inp))
        out.extend(_r5(inp))
    return out
