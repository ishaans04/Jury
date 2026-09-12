"""Scoring. PRD §9, formula-for-formula.

The scoring model exists to make the numbers defensible: every input is
countable, and every weight is published in docs/SCORING.md.

Pure module. Callers pass data in; nothing here touches a database.
"""
import math
from dataclasses import dataclass, field

from jury.schemas.enums import AssumptionStatus, Criticality, Decision, Direction
from jury.schemas.verdict import ConfidenceComponents

# ── PRD §9.1, exact published values ─────────────────────────────────────────
TIER_WEIGHTS: dict[int, float] = {1: 1.00, 2: 0.80, 3: 0.55, 4: 0.30}

# Spec §26.4: tier-4 forum anecdote is discounted for variables where stated
# intent is known-unreliable. This only ever narrows tier-4 influence.
_TIER4_WTP_WEIGHT = 0.15
_TIER4_WTP_EXACT = frozenset({"price_monthly", "take_rate"})
_TIER4_WTP_PREFIXES = ("wtp_",)

# ── PRD §9.3 / spec §26.3 ────────────────────────────────────────────────────
# Chosen by judgement, not fitted to data. Published in docs/SCORING.md.
# Defined once here so the backtest can vary them without touching logic.
CONFIDENCE_WEIGHTS: dict[str, float] = {
    "coverage": 0.30,
    "mean_strength": 0.30,
    "contradiction": 0.20,
    "open_critical": 0.20,
}

STRENGTH_THRESHOLD = 0.35          # PRD §9.2 status table
_CRITICAL = frozenset({Criticality.BLOCKING, Criticality.HIGH})
_OPEN_STATUSES = frozenset({AssumptionStatus.NO_EVIDENCE, AssumptionStatus.UNCERTAIN})


@dataclass(frozen=True, slots=True)
class EvidenceLike:
    """The subset of an evidence row that scoring needs. Keeps the engine pure."""
    tier: int
    confidence: float
    direction: Direction
    variable: str | None = None


@dataclass(frozen=True, slots=True)
class AssumptionLike:
    id: str
    class_key: str | None
    criticality: Criticality
    evidence: list[EvidenceLike] = field(default_factory=list)
    has_unresolved_conflict: bool = False


def tier_weight(tier: int, variable: str | None = None) -> float:
    """Weight for one evidence item. Raises KeyError on tier 5 — a model prior
    is not evidence and must never be scorable (P1)."""
    base = TIER_WEIGHTS[tier]
    if tier == 4 and variable:
        v = variable.lower()
        if v in _TIER4_WTP_EXACT or v.startswith(_TIER4_WTP_PREFIXES):
            return _TIER4_WTP_WEIGHT
    return base


def raw_signal(items: list[EvidenceLike]) -> float:
    """support - refute, each side weighted by tier and item confidence."""
    total = 0.0
    for i in items:
        w = tier_weight(i.tier, i.variable) * i.confidence
        total += w if i.direction is Direction.SUPPORTS else -w
    return total


def strength(items: list[EvidenceLike]) -> float:
    """tanh(|raw| / 2) -> 0..1 with diminishing returns (PRD §9.2).

    Independent corroboration raises strength because dedup (P10) guarantees
    the items come from distinct sources.
    """
    if not items:
        return 0.0
    return math.tanh(abs(raw_signal(items)) / 2.0)


def assign_status(items: list[EvidenceLike],
                  has_unresolved_conflict: bool) -> AssumptionStatus:
    """PRD §9.2 status table. Unresolved conflict dominates every other outcome:
    disagreement is a reason to know less, not a reason to pick a side."""
    if has_unresolved_conflict:
        return AssumptionStatus.CONTESTED
    if not items:
        return AssumptionStatus.NO_EVIDENCE
    s = strength(items)
    if s < STRENGTH_THRESHOLD:
        return AssumptionStatus.UNCERTAIN
    return (AssumptionStatus.SUPPORTED if raw_signal(items) > 0
            else AssumptionStatus.REFUTED)


def coverage(classes: list[tuple[str, float]],
             assumptions: list[AssumptionLike]) -> float:
    """Weighted fraction of the archetype's assumption classes that carry evidence.

    PRD §9.3:
        coverage = sum(crit_weight(c) * covered(c)) / sum(crit_weight(c))
        covered(c) = 1 if >=1 assumption in c has >=1 evidence item

    P4: `classes` is the hand-seeded external denominator. Passing a
    runtime-generated list here would hollow out the whole product.
    """
    denominator = sum(w for _, w in classes)
    if denominator == 0:
        return 0.0
    with_evidence = {a.class_key for a in assumptions if a.class_key and a.evidence}
    numerator = sum(w for key, w in classes if key in with_evidence)
    return numerator / denominator


def evidence_confidence(
    classes: list[tuple[str, float]],
    assumptions: list[AssumptionLike],
    unresolved_conflicts: int,
) -> tuple[float, ConfidenceComponents]:
    """Evidence Confidence 0-100 plus its four components (PRD §9.3).

    Returns both because the UI must always render the decomposition: a number
    with a visible decomposition is defensible, one without is not.

    Deviation from the literal brief pseudocode: a totally empty record
    (no assumptions gathered at all) is special-cased to score 0. Without
    this guard, `contradiction` and `open_critical` vacuously read "perfect"
    when there are zero critical assumptions to be open or contradicted,
    handing 40% of the total score to a record where nothing was
    investigated. That is distinct from the (intentional, per PRD) case
    where an archetype genuinely has no blocking/high assumption classes —
    this guard only fires when `assumptions` itself is empty.
    """
    if not assumptions:
        return 0.0, ConfidenceComponents(
            coverage=0.0, mean_strength=0.0, contradiction=0.0, open_critical=0.0,
        )

    cov = coverage(classes, assumptions)

    critical = [a for a in assumptions if a.criticality in _CRITICAL]
    mean_strength = (sum(strength(a.evidence) for a in critical) / len(critical)
                     if critical else 0.0)

    investigated_critical = [a for a in critical if a.evidence]
    contradiction = unresolved_conflicts / max(1, len(investigated_critical))

    open_count = sum(
        1 for a in critical
        if assign_status(a.evidence, a.has_unresolved_conflict) in _OPEN_STATUSES
    )
    open_critical = open_count / max(1, len(critical))

    components = ConfidenceComponents(
        coverage=cov,
        mean_strength=mean_strength,
        contradiction=contradiction,
        open_critical=open_critical,
    )

    total = 100.0 * (
        CONFIDENCE_WEIGHTS["coverage"] * cov
        + CONFIDENCE_WEIGHTS["mean_strength"] * mean_strength
        + CONFIDENCE_WEIGHTS["contradiction"] * (1.0 - min(1.0, contradiction))
        + CONFIDENCE_WEIGHTS["open_critical"] * (1.0 - open_critical)
    )
    return max(0.0, min(100.0, total)), components


# ── the verdict gate: PRD §9.4 ───────────────────────────────────────────────
# The Jury's decision is separate from Evidence Confidence and is gated by it.
# P5: below threshold, PROCEED and STOP are structurally unreachable.

COVERAGE_GATE = 0.70
CONFIDENCE_GATE = 45.0


@dataclass(frozen=True, slots=True)
class GateResult:
    decision: Decision
    gate_triggered: str | None


def apply_gate(
    coverage: float,
    assumptions: list[AssumptionLike],
    confidence: float,
    has_viable_adjacent: bool,
    economics_viable: bool,
    unresolved_critical: int,
) -> GateResult:
    """Return the verdict, or HUNG_JURY plus the condition that fired.

    A STOP on thin evidence is as irresponsible as a PROCEED on thin evidence,
    and the gate makes both impossible to express (PRD §9.5).
    """
    if coverage < COVERAGE_GATE:
        return GateResult(Decision.HUNG_JURY, "coverage_below_0.70")

    blocking = [a for a in assumptions if a.criticality is Criticality.BLOCKING]
    for a in blocking:
        if assign_status(a.evidence, a.has_unresolved_conflict) in _OPEN_STATUSES:
            return GateResult(Decision.HUNG_JURY, "blocking_assumption_unresolved")

    if confidence < CONFIDENCE_GATE:
        return GateResult(Decision.HUNG_JURY, "confidence_below_45")

    # Past the gate. PRD §9.4 decision table.
    statuses = {
        a.id: assign_status(a.evidence, a.has_unresolved_conflict) for a in assumptions
    }
    refuted_blocking = [a for a in blocking
                        if statuses[a.id] is AssumptionStatus.REFUTED]
    refuted_critical = [a for a in assumptions
                        if a.criticality in _CRITICAL
                        and statuses[a.id] is AssumptionStatus.REFUTED]

    if refuted_blocking and not has_viable_adjacent:
        return GateResult(Decision.STOP, None)
    if refuted_critical and has_viable_adjacent:
        return GateResult(Decision.PIVOT, None)

    all_blocking_supported = all(
        statuses[a.id] is AssumptionStatus.SUPPORTED for a in blocking
    )
    if all_blocking_supported and economics_viable and unresolved_critical == 0:
        return GateResult(Decision.PROCEED, None)

    # Past the gate but not clean enough for PROCEED, and no refutation to act on.
    return GateResult(Decision.PIVOT, None)
