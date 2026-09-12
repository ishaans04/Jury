import math

import pytest

from jury.engines.scoring import (
    CONFIDENCE_WEIGHTS, TIER_WEIGHTS, AssumptionLike, EvidenceLike,
    assign_status, coverage, evidence_confidence, strength, tier_weight,
)
from jury.schemas.enums import AssumptionStatus, Criticality, Direction


def ev(tier=1, conf=1.0, direction="supports", variable=None) -> EvidenceLike:
    return EvidenceLike(tier=tier, confidence=conf,
                        direction=Direction(direction), variable=variable)


# ── tier weights: PRD §9.1 exact values ──────────────────────────────────────
def test_tier_weights_are_the_published_values():
    assert TIER_WEIGHTS == {1: 1.00, 2: 0.80, 3: 0.55, 4: 0.30}


def test_tier_five_has_no_weight_and_is_not_persistable():
    with pytest.raises(KeyError):
        _ = TIER_WEIGHTS[5]


def test_tier4_wtp_variables_are_discounted():
    """Spec §26.4: stated willingness to pay is notoriously unreliable."""
    assert tier_weight(4, "price_monthly") == 0.15
    assert tier_weight(4, "wtp_annual") == 0.15
    assert tier_weight(4, "take_rate") == 0.15


def test_tier4_other_variables_keep_the_baseline():
    assert tier_weight(4, "delivery_cost") == 0.30
    assert tier_weight(4, None) == 0.30


def test_the_override_never_widens_tier4_influence():
    for v in ("price_monthly", "wtp_x", "take_rate", "anything", None):
        assert tier_weight(4, v) <= 0.30


def test_higher_tiers_are_unaffected_by_the_wtp_override():
    assert tier_weight(1, "price_monthly") == 1.00
    assert tier_weight(2, "price_monthly") == 0.80


# ── strength: PRD §9.2 ───────────────────────────────────────────────────────
def test_no_evidence_is_zero_strength():
    assert strength([]) == 0.0


def test_single_tier1_support_matches_hand_computation():
    # raw = 1.00 * 1.0 = 1.0 ; tanh(0.5)
    assert strength([ev(1, 1.0)]) == pytest.approx(math.tanh(0.5))


def test_opposing_equal_evidence_cancels_to_zero():
    assert strength([ev(1, 1.0, "supports"), ev(1, 1.0, "refutes")]) == pytest.approx(0.0)


def test_strength_uses_absolute_raw_so_refutation_is_as_strong_as_support():
    a = strength([ev(1, 1.0, "supports"), ev(1, 1.0, "supports")])
    b = strength([ev(1, 1.0, "refutes"), ev(1, 1.0, "refutes")])
    assert a == pytest.approx(b)


def test_independent_corroboration_raises_strength_with_diminishing_returns():
    """P10 guarantees distinct sources, so more items legitimately raise strength —
    but tanh means the fourth source adds less than the second."""
    one, two, three = (strength([ev(1, 1.0)] * n) for n in (1, 2, 3))
    assert one < two < three
    assert (two - one) > (three - two)


def test_strength_is_bounded_to_unit_interval():
    assert 0.0 <= strength([ev(1, 1.0)] * 50) <= 1.0


def test_mixed_tiers_match_hand_computation():
    # raw = (1.00*1.0) + (0.55*0.8) - (0.30*0.5) = 1.0 + 0.44 - 0.15 = 1.29
    items = [ev(1, 1.0, "supports"), ev(3, 0.8, "supports"), ev(4, 0.5, "refutes")]
    assert strength(items) == pytest.approx(math.tanh(1.29 / 2))


# ── status assignment: PRD §9.2 table ────────────────────────────────────────
def test_zero_items_is_no_evidence():
    assert assign_status([], False) is AssumptionStatus.NO_EVIDENCE


def test_weak_evidence_is_uncertain():
    # tier 4 non-wtp, low confidence: raw = 0.30*0.2 = 0.06, tanh(0.03) ~ 0.03 < 0.35
    assert assign_status([ev(4, 0.2)], False) is AssumptionStatus.UNCERTAIN


def test_strong_positive_is_supported():
    assert assign_status([ev(1, 1.0), ev(1, 1.0)], False) is AssumptionStatus.SUPPORTED


def test_strong_negative_is_refuted():
    items = [ev(1, 1.0, "refutes"), ev(1, 1.0, "refutes")]
    assert assign_status(items, False) is AssumptionStatus.REFUTED


def test_unresolved_conflict_beats_every_other_status():
    """PRD §9.2: 'unresolved conflict present' -> contested, whatever the arithmetic says."""
    assert assign_status([ev(1, 1.0), ev(1, 1.0)], True) is AssumptionStatus.CONTESTED
    assert assign_status([], True) is AssumptionStatus.CONTESTED


def test_status_boundary_is_exactly_0_35():
    """strength >= 0.35 flips uncertain -> supported. Verify the boundary is inclusive."""
    # tanh(raw/2) = 0.35  ->  raw = 2*atanh(0.35)
    raw = 2 * math.atanh(0.35)
    items = [ev(1, raw)]          # tier 1 weight 1.0, so raw == confidence
    assert strength(items) == pytest.approx(0.35)
    assert assign_status(items, False) is AssumptionStatus.SUPPORTED


# ── coverage: PRD §9.3 ───────────────────────────────────────────────────────
def asm(class_key, criticality="blocking", n_evidence=0, conflict=False) -> AssumptionLike:
    return AssumptionLike(id=class_key or "x", class_key=class_key,
                          criticality=Criticality(criticality),
                          evidence=[ev(1, 1.0)] * n_evidence,
                          has_unresolved_conflict=conflict)


def test_coverage_is_weighted_by_criticality_not_counted():
    classes = [("a.x", 1.0), ("a.y", 0.6), ("a.z", 0.3)]
    # only the 1.0-weight class is covered -> 1.0 / 1.9
    got = coverage(classes, [asm("a.x", n_evidence=1)])
    assert got == pytest.approx(1.0 / 1.9)


def test_a_class_needs_at_least_one_evidence_item_to_count_as_covered():
    """PRD §9.3: covered(c) = 1 if >=1 assumption in c has >=1 evidence item.
    An assumption with no evidence does NOT cover its class."""
    classes = [("a.x", 1.0)]
    assert coverage(classes, [asm("a.x", n_evidence=0)]) == 0.0
    assert coverage(classes, [asm("a.x", n_evidence=1)]) == 1.0


def test_full_coverage_is_one():
    classes = [("a.x", 1.0), ("a.y", 0.6)]
    assert coverage(classes, [asm("a.x", n_evidence=1), asm("a.y", n_evidence=1)]) == 1.0


def test_coverage_of_an_empty_denominator_is_zero_not_a_crash():
    assert coverage([], []) == 0.0


def test_unclassified_assumptions_do_not_contribute_to_coverage():
    """Coverage is measured against the external denominator only (P4)."""
    classes = [("a.x", 1.0)]
    assert coverage(classes, [asm(None, n_evidence=5)]) == 0.0


# ── evidence confidence: PRD §9.3 ────────────────────────────────────────────
def test_confidence_weights_are_the_published_split():
    assert CONFIDENCE_WEIGHTS == {"coverage": 0.30, "mean_strength": 0.30,
                                  "contradiction": 0.20, "open_critical": 0.20}


def test_weights_sum_to_one():
    assert sum(CONFIDENCE_WEIGHTS.values()) == pytest.approx(1.0)


def test_perfect_record_scores_one_hundred():
    classes = [("a.x", 1.0)]
    assumptions = [asm("a.x", "blocking", n_evidence=6)]
    total, comp = evidence_confidence(classes, assumptions, unresolved_conflicts=0)
    assert comp.coverage == 1.0
    assert comp.contradiction == 0.0
    assert comp.open_critical == 0.0
    assert total == pytest.approx(100.0, abs=0.5)


def test_empty_record_scores_zero():
    total, comp = evidence_confidence([("a.x", 1.0)], [], unresolved_conflicts=0)
    assert total == pytest.approx(0.0)
    assert comp.coverage == 0.0


def test_components_are_returned_alongside_the_total():
    """PRD §9.3: the UI always displays the four components. A number without a
    visible decomposition is not defensible."""
    _, comp = evidence_confidence([("a.x", 1.0)], [asm("a.x", n_evidence=2)],
                                  unresolved_conflicts=1)
    assert set(comp.model_dump()) == {"coverage", "mean_strength",
                                      "contradiction", "open_critical"}


def test_contradiction_is_clamped_at_one():
    """More unresolved conflicts than critical assumptions must not make the
    term negative once inverted."""
    total, comp = evidence_confidence([("a.x", 1.0)], [asm("a.x", n_evidence=1)],
                                      unresolved_conflicts=99)
    assert comp.contradiction >= 1.0
    assert total >= 0.0


def test_mean_strength_only_considers_blocking_and_high():
    """PRD §9.3: mean over assumptions where criticality in {blocking, high}."""
    classes = [("a.x", 1.0), ("a.y", 0.3)]
    strong_blocking = asm("a.x", "blocking", n_evidence=6)
    weak_low = AssumptionLike(id="y", class_key="a.y", criticality=Criticality.LOW,
                              evidence=[ev(4, 0.1)], has_unresolved_conflict=False)
    _, comp = evidence_confidence(classes, [strong_blocking, weak_low],
                                  unresolved_conflicts=0)
    assert comp.mean_strength == pytest.approx(strength(strong_blocking.evidence))


def test_open_critical_counts_no_evidence_and_uncertain():
    classes = [("a.x", 1.0), ("a.y", 1.0)]
    covered = asm("a.x", "blocking", n_evidence=6)
    bare = asm("a.y", "blocking", n_evidence=0)
    _, comp = evidence_confidence(classes, [covered, bare], unresolved_conflicts=0)
    assert comp.open_critical == pytest.approx(0.5)


def test_contradiction_earns_nothing_when_no_critical_assumption_was_investigated():
    """A clean contradiction score must be earned by checking, not by absence.

    Otherwise a run whose chairs all failed would display "Contradiction:
    perfect" beside "Coverage: 0" — an unearned green tick on a hung jury.
    """
    classes = [("a.x", 1.0)]
    total, comp = evidence_confidence(classes, [asm("a.x", n_evidence=0)],
                                      unresolved_conflicts=0)
    assert comp.contradiction == 1.0
    assert total == pytest.approx(0.0)


def test_confidence_is_bounded_to_0_100():
    classes = [("a.x", 1.0)]
    for n in (0, 1, 3, 20):
        total, _ = evidence_confidence(classes, [asm("a.x", n_evidence=n)],
                                       unresolved_conflicts=n)
        assert 0.0 <= total <= 100.0
