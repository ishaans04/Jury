import pytest

from jury.engines.conflict import (
    AssumptionForConflict, ConflictInput, EvidenceForConflict, detect_conflicts,
)
from jury.schemas.enums import Chair, ConflictKind, ConflictRule, Criticality, Direction, Origin
from jury.schemas.scope import Scope

IN_SMB = Scope(geo="IN", segment="smb")
US_ENT = Scope(geo="US", segment="enterprise")


def e(eid="e1", chair="market", direction="supports", variable=None, value=None,
      tier=1, scope=IN_SMB, vmin=None, vmax=None) -> EvidenceForConflict:
    return EvidenceForConflict(id=eid, chair=Chair(chair), direction=Direction(direction),
                               variable=variable, value_num=value, value_min=vmin,
                               value_max=vmax, tier=tier, scope=scope)


def a(origin="founder", criticality="blocking", var=None, val=None) -> AssumptionForConflict:
    return AssumptionForConflict(id="a1", origin=Origin(origin),
                                 criticality=Criticality(criticality),
                                 asserted_variable=var, asserted_value=val)


def only(kinds, conflicts):
    return [c for c in conflicts if c.kind in kinds]


# ── R1: chair vs chair, direction ────────────────────────────────────────────
def test_r1_fires_on_opposing_tier1_evidence_in_overlapping_scope():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", direction="supports", tier=1),
                  e("e2", chair="customer", direction="refutes", tier=1)])])
    r1 = [c for c in got if c.rule is ConflictRule.R1]
    assert len(r1) == 1
    assert r1[0].kind is ConflictKind.CHAIR_VS_CHAIR
    assert r1[0].triggers_cross_exam is True


def test_r1_ignores_tier3_and_below():
    """PRD §16.3 R1 requires BOTH items at tier <= 2. Forum anecdote does not
    get to start a fight with a pricing page."""
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", direction="supports", tier=1),
                  e("e2", direction="refutes", tier=4)])])
    assert not [c for c in got if c.rule is ConflictRule.R1]


def test_r1_ignores_non_overlapping_scope():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", direction="supports", tier=1, scope=IN_SMB),
                  e("e2", direction="refutes", tier=1, scope=US_ENT)])])
    assert not [c for c in got if c.rule is ConflictRule.R1]


def test_r1_does_not_trigger_cross_exam_for_medium_criticality():
    got = detect_conflicts([ConflictInput(
        assumption=a(criticality="medium"), target_scope=IN_SMB,
        evidence=[e("e1", direction="supports", tier=1),
                  e("e2", direction="refutes", tier=2)])])
    r1 = [c for c in got if c.rule is ConflictRule.R1]
    assert len(r1) == 1 and r1[0].triggers_cross_exam is False


def test_r1_ignores_a_low_tier_supporting_item():
    """Both items must be tier <= 2. The existing test only exercises a
    low-tier REFUTES item, so a filter applied to just one side would pass
    it. Forum anecdote cannot start a fight from either direction."""
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", direction="supports", tier=4),
                  e("e2", direction="refutes", tier=1)])])
    assert not [c for c in got if c.rule is ConflictRule.R1]


# ── R2: numeric divergence beyond the tolerance band ────────────────────────
def test_r2_fires_beyond_the_ten_percent_band():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=100.0),
                  e("e2", chair="customer", variable="price_monthly", value=200.0)])])
    r2 = [c for c in got if c.rule is ConflictRule.R2]
    assert len(r2) == 1 and r2[0].kind is ConflictKind.CHAIR_VS_CHAIR


def test_r2_tolerates_values_inside_the_band():
    """105 vs 100 is 5% - measurement noise, not a contradiction."""
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=100.0),
                  e("e2", variable="price_monthly", value=105.0)])])
    assert not [c for c in got if c.rule is ConflictRule.R2]


def test_r2_boundary_exactly_ten_percent_does_not_fire():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=100.0),
                  e("e2", variable="price_monthly", value=110.0)])])
    assert not [c for c in got if c.rule is ConflictRule.R2]


def test_r2_ignores_different_variables():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=100.0),
                  e("e2", variable="delivery_cost", value=900.0)])])
    assert not [c for c in got if c.rule is ConflictRule.R2]


def test_r2_ignores_non_overlapping_scope():
    """The exact false positive PRD §12.1 warns about: Rs 149 US-SMB vs Rs 500 IN-enterprise."""
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=149.0, scope=US_ENT),
                  e("e2", variable="price_monthly", value=500.0, scope=IN_SMB)])])
    assert not [c for c in got if c.rule is ConflictRule.R2]


def test_r2_uses_ranges_when_present_and_overlapping_ranges_do_not_conflict():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", vmin=100.0, vmax=200.0),
                  e("e2", variable="price_monthly", vmin=180.0, vmax=300.0)])])
    assert not [c for c in got if c.rule is ConflictRule.R2]


def test_r2_fires_on_disjoint_ranges():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", vmin=100.0, vmax=150.0),
                  e("e2", variable="price_monthly", vmin=400.0, vmax=500.0)])])
    assert [c for c in got if c.rule is ConflictRule.R2]


# ── R3: founder vs world. "The rule that earns the product its existence." ──
def test_r3_fires_beyond_twenty_five_percent_divergence():
    got = detect_conflicts([ConflictInput(
        assumption=a(origin="founder", var="price_monthly", val=499.0),
        target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=149.0)])])
    r3 = [c for c in got if c.rule is ConflictRule.R3]
    assert len(r3) == 1
    assert r3[0].kind is ConflictKind.FOUNDER_VS_WORLD
    assert r3[0].triggers_cross_exam is True         # R3 ALWAYS triggers


def test_r3_always_triggers_cross_exam_even_at_low_criticality():
    got = detect_conflicts([ConflictInput(
        assumption=a(origin="founder", criticality="low", var="price_monthly", val=499.0),
        target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=149.0)])])
    r3 = [c for c in got if c.rule is ConflictRule.R3]
    assert r3 and r3[0].triggers_cross_exam is True


def test_r3_tolerates_divergence_inside_twenty_five_percent():
    got = detect_conflicts([ConflictInput(
        assumption=a(origin="founder", var="price_monthly", val=120.0),
        target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=100.0)])])
    assert not [c for c in got if c.rule is ConflictRule.R3]


def test_r3_does_not_fire_for_discovered_assumptions():
    """P2: only FOUNDER assertions can lose to the world."""
    got = detect_conflicts([ConflictInput(
        assumption=AssumptionForConflict(id="a1", origin=Origin.DISCOVERED,
                                         criticality=Criticality.BLOCKING,
                                         asserted_variable="price_monthly",
                                         asserted_value=499.0),
        target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=149.0)])])
    assert not [c for c in got if c.rule is ConflictRule.R3]


def test_r3_divergence_is_relative_to_evidence_not_to_the_claim():
    """PRD §16.3: abs(V - E) / E. The world is the denominator."""
    # V=100, E=50 -> |50|/50 = 1.0 > 0.25, fires
    got = detect_conflicts([ConflictInput(
        assumption=a(origin="founder", var="x", val=100.0), target_scope=IN_SMB,
        evidence=[e("e1", variable="x", value=50.0)])])
    assert [c for c in got if c.rule is ConflictRule.R3]


def test_r3_handles_zero_evidence_value_without_dividing_by_zero():
    got = detect_conflicts([ConflictInput(
        assumption=a(origin="founder", var="x", val=100.0), target_scope=IN_SMB,
        evidence=[e("e1", variable="x", value=0.0)])])
    assert isinstance(got, list)      # must not raise


def test_r3_does_not_fire_at_exactly_twenty_five_percent():
    """The threshold is > 0.25, not >=. A founder claiming 125 against
    evidence of 100 is exactly at the band and is not yet contradicted."""
    got = detect_conflicts([ConflictInput(
        assumption=a(origin="founder", var="price_monthly", val=125.0),
        target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=100.0)])])
    assert not [c for c in got if c.rule is ConflictRule.R3]


def test_r3_fires_just_beyond_twenty_five_percent():
    got = detect_conflicts([ConflictInput(
        assumption=a(origin="founder", var="price_monthly", val=125.5),
        target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=100.0)])])
    assert [c for c in got if c.rule is ConflictRule.R3]


# ── R4: silence is a finding ────────────────────────────────────────────────
def test_r4_fires_for_a_critical_assumption_with_no_evidence():
    got = detect_conflicts([ConflictInput(assumption=a(criticality="blocking"),
                                          target_scope=IN_SMB, evidence=[])])
    r4 = [c for c in got if c.rule is ConflictRule.R4]
    assert len(r4) == 1
    assert r4[0].kind is ConflictKind.NO_EVIDENCE
    assert r4[0].triggers_cross_exam is False     # nothing to debate


def test_r4_does_not_fire_for_low_criticality():
    got = detect_conflicts([ConflictInput(assumption=a(criticality="low"),
                                          target_scope=IN_SMB, evidence=[])])
    assert not [c for c in got if c.rule is ConflictRule.R4]


def test_r4_does_not_fire_when_any_evidence_exists():
    got = detect_conflicts([ConflictInput(assumption=a(), target_scope=IN_SMB,
                                          evidence=[e("e1")])])
    assert not [c for c in got if c.rule is ConflictRule.R4]


# ── R5: scope gap is a gap, not a contradiction ─────────────────────────────
def test_r5_fires_when_no_evidence_covers_the_target_scope():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", scope=US_ENT), e("e2", scope=US_ENT)])])
    r5 = [c for c in got if c.rule is ConflictRule.R5]
    assert len(r5) == 1
    assert r5[0].kind is ConflictKind.SCOPE_GAP
    assert r5[0].triggers_cross_exam is False     # reported as a gap (F9)


def test_r5_does_not_fire_when_global_evidence_covers_the_target():
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=IN_SMB,
        evidence=[e("e1", scope=Scope(geo="GLOBAL", segment="smb"))])])
    assert not [c for c in got if c.rule is ConflictRule.R5]


def test_r5_does_not_fire_when_there_is_no_evidence_at_all():
    """With zero evidence R4 is the correct finding, not R5."""
    got = detect_conflicts([ConflictInput(assumption=a(), target_scope=IN_SMB,
                                          evidence=[])])
    assert not [c for c in got if c.rule is ConflictRule.R5]
    assert [c for c in got if c.rule is ConflictRule.R4]


def test_r5_fires_when_evidence_is_narrower_than_the_target_scope():
    """R5 asks whether evidence COVERS the founder's target, which is
    directional. Evidence about IN-smb does not cover a GLOBAL-smb target,
    even though the two scopes overlap. Using symmetric overlap here would
    silently accept partial evidence as full coverage."""
    got = detect_conflicts([ConflictInput(
        assumption=a(), target_scope=Scope(geo="GLOBAL", segment="smb"),
        evidence=[e("e1", scope=Scope(geo="IN", segment="smb"))])])
    assert [c for c in got if c.rule is ConflictRule.R5]


# ── engine-level properties ─────────────────────────────────────────────────
def test_detection_is_deterministic_across_repeated_calls():
    """F9: deterministic. Same input, same output, same order."""
    inp = [ConflictInput(
        assumption=a(origin="founder", var="price_monthly", val=499.0),
        target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=149.0, tier=1),
                  e("e2", chair="customer", variable="price_monthly",
                    value=600.0, direction="refutes", tier=2)])]
    first = detect_conflicts(inp)
    for _ in range(20):
        again = detect_conflicts(inp)
        assert [(c.rule, c.kind, c.left_ref, c.right_ref) for c in again] == \
               [(c.rule, c.kind, c.left_ref, c.right_ref) for c in first]


def test_no_conflicts_on_a_clean_record():
    got = detect_conflicts([ConflictInput(
        assumption=a(origin="founder", var="price_monthly", val=150.0),
        target_scope=IN_SMB,
        evidence=[e("e1", variable="price_monthly", value=149.0, tier=1),
                  e("e2", chair="customer", variable="price_monthly", value=152.0, tier=1)])])
    assert got == []


def test_severity_is_derived_from_criticality():
    got = detect_conflicts([ConflictInput(assumption=a(criticality="blocking"),
                                          target_scope=IN_SMB, evidence=[])])
    assert got[0].severity == "critical"
