import itertools

import pytest

from jury.engines.scoring import AssumptionLike, EvidenceLike, apply_gate
from jury.schemas.enums import Criticality, Decision, Direction


def ev(direction="supports", tier=1, conf=1.0) -> EvidenceLike:
    return EvidenceLike(tier=tier, confidence=conf, direction=Direction(direction))


def blocking(status="supported") -> AssumptionLike:
    """Build a blocking assumption whose computed status is what we asked for."""
    if status == "supported":
        items = [ev("supports")] * 3
    elif status == "refuted":
        items = [ev("refutes")] * 3
    elif status == "uncertain":
        items = [ev("supports", tier=4, conf=0.1)]
    else:                                     # no_evidence
        items = []
    return AssumptionLike(id=status, class_key="a.x",
                          criticality=Criticality.BLOCKING, evidence=items)


# ── the three gate conditions ────────────────────────────────────────────────
def test_low_coverage_hangs_the_jury():
    r = apply_gate(coverage=0.69, assumptions=[blocking("supported")], confidence=90.0,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert r.decision is Decision.HUNG_JURY
    assert r.gate_triggered == "coverage_below_0.70"


def test_coverage_exactly_at_threshold_does_not_hang():
    r = apply_gate(coverage=0.70, assumptions=[blocking("supported")], confidence=90.0,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert r.decision is not Decision.HUNG_JURY


def test_blocking_assumption_with_no_evidence_hangs_the_jury():
    r = apply_gate(coverage=0.99, assumptions=[blocking("no_evidence")], confidence=99.0,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert r.decision is Decision.HUNG_JURY
    assert r.gate_triggered == "blocking_assumption_unresolved"


def test_blocking_assumption_merely_uncertain_hangs_the_jury():
    r = apply_gate(coverage=0.99, assumptions=[blocking("uncertain")], confidence=99.0,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert r.decision is Decision.HUNG_JURY
    assert r.gate_triggered == "blocking_assumption_unresolved"


def test_low_confidence_hangs_the_jury():
    r = apply_gate(coverage=0.99, assumptions=[blocking("supported")], confidence=44.9,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert r.decision is Decision.HUNG_JURY
    assert r.gate_triggered == "confidence_below_45"


def test_confidence_exactly_45_does_not_hang():
    r = apply_gate(coverage=0.99, assumptions=[blocking("supported")], confidence=45.0,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert r.decision is not Decision.HUNG_JURY


# ── the unreachability proof (F12 acceptance criterion) ──────────────────────
def test_proceed_and_stop_are_structurally_unreachable_below_threshold():
    """P5 / F12: below threshold, PROCEED and STOP must be UNREACHABLE, not unlikely.

    Brute-force every combination of the three gate conditions together with
    every downstream input that could otherwise produce PROCEED or STOP.
    """
    sub_coverages = [0.0, 0.35, 0.699]
    sub_confidences = [0.0, 20.0, 44.999]
    statuses = ["supported", "refuted", "uncertain", "no_evidence"]

    checked = 0
    for cov, conf, status, adjacent, viable, unresolved in itertools.product(
        sub_coverages, sub_confidences, statuses, [True, False], [True, False], [0, 3]
    ):
        r = apply_gate(coverage=cov, assumptions=[blocking(status)], confidence=conf,
                       has_viable_adjacent=adjacent, economics_viable=viable,
                       unresolved_critical=unresolved)
        assert r.decision is Decision.HUNG_JURY, (cov, conf, status)
        assert r.decision not in (Decision.PROCEED, Decision.STOP)
        checked += 1
    assert checked == 3 * 3 * 4 * 2 * 2 * 2   # 288 combinations


def test_any_single_failing_condition_is_sufficient_to_hang():
    """The gate is a disjunction: passing two conditions does not rescue the third."""
    ok = dict(coverage=0.99, assumptions=[blocking("supported")], confidence=99.0,
              has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert apply_gate(**ok).decision is not Decision.HUNG_JURY
    assert apply_gate(**{**ok, "coverage": 0.1}).decision is Decision.HUNG_JURY
    assert apply_gate(**{**ok, "confidence": 1.0}).decision is Decision.HUNG_JURY
    assert apply_gate(**{**ok, "assumptions": [blocking("no_evidence")]}
                      ).decision is Decision.HUNG_JURY


# ── post-gate verdict table (PRD §9.4) ───────────────────────────────────────
def test_refuted_blocking_with_no_adjacency_is_stop():
    r = apply_gate(coverage=0.9, assumptions=[blocking("refuted")], confidence=80.0,
                   has_viable_adjacent=False, economics_viable=False, unresolved_critical=0)
    assert r.decision is Decision.STOP


def test_refuted_blocking_with_a_viable_adjacency_is_pivot():
    r = apply_gate(coverage=0.9, assumptions=[blocking("refuted")], confidence=80.0,
                   has_viable_adjacent=True, economics_viable=False, unresolved_critical=0)
    assert r.decision is Decision.PIVOT


def test_all_supported_and_viable_and_unconflicted_is_proceed():
    r = apply_gate(coverage=0.9, assumptions=[blocking("supported")], confidence=80.0,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert r.decision is Decision.PROCEED


def test_unresolved_critical_conflict_blocks_proceed():
    """PRD §9.4 PROCEED requires 'no unresolved critical conflicts'."""
    r = apply_gate(coverage=0.9, assumptions=[blocking("supported")], confidence=80.0,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=1)
    assert r.decision is not Decision.PROCEED


def test_non_viable_economics_blocks_proceed():
    r = apply_gate(coverage=0.9, assumptions=[blocking("supported")], confidence=80.0,
                   has_viable_adjacent=True, economics_viable=False, unresolved_critical=0)
    assert r.decision is not Decision.PROCEED


def test_gate_triggered_is_none_when_the_gate_did_not_fire():
    r = apply_gate(coverage=0.9, assumptions=[blocking("supported")], confidence=80.0,
                   has_viable_adjacent=True, economics_viable=True, unresolved_critical=0)
    assert r.gate_triggered is None


def test_high_criticality_refuted_also_permits_pivot():
    """PRD §9.4 PIVOT: '>=1 blocking OR high assumption refuted' with adjacency."""
    high_refuted = AssumptionLike(id="h", class_key="a.y", criticality=Criticality.HIGH,
                                  evidence=[ev("refutes")] * 3)
    r = apply_gate(coverage=0.9, assumptions=[blocking("supported"), high_refuted],
                   confidence=80.0, has_viable_adjacent=True, economics_viable=True,
                   unresolved_critical=0)
    assert r.decision is Decision.PIVOT
