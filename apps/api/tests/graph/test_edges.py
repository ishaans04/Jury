"""jury.graph.edges. Task 5.1. PRD §7.6, §16.4."""
from jury.graph.edges import (MAX_CROSS_EXAM_CONFLICTS, route_after_reconcile,
                              select_conflicts_for_cross_exam)


def c(rule="R3", kind="founder_vs_world", severity="critical", triggers=True, cid="c1"):
    return {"id": cid, "rule": rule, "kind": kind, "severity": severity,
            "triggers_cross_exam": triggers, "status": "open"}


def test_no_conflicts_skips_cross_examination_entirely():
    """P7: debate only where conflict exists. Not 'debate, briefly, anyway'."""
    assert route_after_reconcile({"conflicts": []}) == "economics"


def test_a_triggering_conflict_routes_to_cross_examination():
    assert route_after_reconcile({"conflicts": [c()]}) == "cross_exam"


def test_no_evidence_conflicts_alone_do_not_trigger_a_debate():
    """R4 is reported and feeds the gate; there is nothing to argue about."""
    assert route_after_reconcile(
        {"conflicts": [c(rule="R4", kind="no_evidence", triggers=False)]}) == "economics"


def test_scope_gaps_alone_do_not_trigger_a_debate():
    """R5 is a gap, not a contradiction (F9)."""
    assert route_after_reconcile(
        {"conflicts": [c(rule="R5", kind="scope_gap", triggers=False)]}) == "economics"


def test_a_medium_criticality_chair_conflict_does_not_trigger():
    assert route_after_reconcile(
        {"conflicts": [c(rule="R1", kind="chair_vs_chair", severity="medium",
                         triggers=False)]}) == "economics"


def test_at_most_five_conflicts_are_selected():
    """PRD §16.4: 'Hard cap of five conflicts cross-examined per run'."""
    many = [c(cid=f"c{i}") for i in range(12)]
    assert len(select_conflicts_for_cross_exam(many)) == MAX_CROSS_EXAM_CONFLICTS == 5


def test_selection_is_ordered_by_criticality_then_severity():
    pool = [c(cid="low", severity="low"), c(cid="crit", severity="critical"),
            c(cid="high", severity="high")]
    assert [x["id"] for x in select_conflicts_for_cross_exam(pool)] == \
           ["crit", "high", "low"]


def test_r3_founder_vs_world_outranks_a_chair_dispute_at_equal_severity():
    """R3 is the rule that earns the product its existence; if only one conflict
    can be argued, it must be that one."""
    pool = [c(cid="chair", rule="R1", kind="chair_vs_chair", severity="critical"),
            c(cid="founder", rule="R3", kind="founder_vs_world", severity="critical")]
    assert select_conflicts_for_cross_exam(pool)[0]["id"] == "founder"


def test_already_resolved_conflicts_are_not_reselected():
    pool = [{**c(cid="done"), "status": "resolved"}, c(cid="open")]
    assert [x["id"] for x in select_conflicts_for_cross_exam(pool)] == ["open"]


def test_selection_is_deterministic():
    pool = [c(cid=f"c{i}", severity="high") for i in range(8)]
    assert [x["id"] for x in select_conflicts_for_cross_exam(pool)] == \
           [x["id"] for x in select_conflicts_for_cross_exam(pool)]
