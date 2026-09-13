import pytest

from jury.engines.diff import causal_sentence, compute_diff

V1 = {
    "assumptions": {"a-price": {"statement": "pricing_wtp", "status": "uncertain"}},
    "evidence_counts": {"market": {"1": 2}},
    "conflicts": {},
    "parameters": {"price_monthly": {"value": 499.0, "provenance": "founder_asserted"}},
    "breakpoints": {"delivery_cost": 38.0},
    "confidence": {"total": 52.0, "coverage": 0.8, "mean_strength": 0.5,
                   "contradiction": 0.0, "open_critical": 0.2},
    "verdict": "PROCEED",
}

V2 = {
    "assumptions": {"a-price": {"statement": "pricing_wtp", "status": "refuted"}},
    "evidence_counts": {"market": {"1": 2}, "customer": {"4": 3}},
    "conflicts": {},
    "parameters": {"price_monthly": {"value": 249.0, "provenance": "evidence_backed"}},
    "breakpoints": {"delivery_cost": 19.0},
    "confidence": {"total": 61.0, "coverage": 0.9, "mean_strength": 0.5,
                   "contradiction": 0.0, "open_critical": 0.1},
    "verdict": "PIVOT",
}


def types_of(entries):
    return [e.type for e in entries]


def test_first_version_has_no_diff_but_does_not_crash():
    entries = compute_diff(None, V1)
    assert entries == []


def test_status_change_is_detected():
    entries = compute_diff(V1, V2)
    e = next(x for x in entries if x.type == "assumption_status_change")
    assert (e.before, e.after) == ("uncertain", "refuted")
    assert e.subject == "a-price"


def test_parameter_provenance_change_is_detected():
    e = next(x for x in compute_diff(V1, V2)
             if x.type == "parameter_provenance_change")
    assert e.before == "founder_asserted" and e.after == "evidence_backed"
    assert e.detail["value_before"] == 499.0 and e.detail["value_after"] == 249.0


def test_breakpoint_move_is_detected():
    e = next(x for x in compute_diff(V1, V2) if x.type == "breakpoint_moved")
    assert (e.before, e.after) == (38.0, 19.0)


def test_verdict_change_is_detected():
    e = next(x for x in compute_diff(V1, V2) if x.type == "verdict_change")
    assert (e.before, e.after) == ("PROCEED", "PIVOT")


def test_confidence_change_names_which_component_moved():
    """PRD §16.8: 'old -> new, with which of the four components moved'."""
    e = next(x for x in compute_diff(V1, V2) if x.type == "confidence_change")
    assert e.before == 52.0 and e.after == 61.0
    assert set(e.detail["components_moved"]) == {"coverage", "open_critical"}


def test_evidence_added_is_counted_by_chair_and_tier():
    e = next(x for x in compute_diff(V1, V2) if x.type == "evidence_added")
    assert e.detail["by_chair"]["customer"] == 3
    assert e.detail["by_tier"]["4"] == 3


def test_newly_discovered_assumption_is_reported():
    v3 = {**V2, "assumptions": {**V2["assumptions"],
                                "a-new": {"statement": "supply liquidity",
                                          "status": "no_evidence",
                                          "origin": "discovered",
                                          "discovered_by": "precedent"}}}
    e = next(x for x in compute_diff(V2, v3) if x.type == "assumption_discovered")
    assert e.subject == "a-new"
    assert e.detail["discovered_by"] == "precedent"


def test_conflict_resolution_is_reported():
    v1 = {**V1, "conflicts": {"c1": {"status": "open", "kind": "founder_vs_world",
                                     "conceding_chair": None}}}
    v2 = {**V2, "conflicts": {"c1": {"status": "conceded", "kind": "founder_vs_world",
                                     "conceding_chair": "market"}}}
    e = next(x for x in compute_diff(v1, v2) if x.type == "conflict_resolved")
    assert e.after == "conceded"
    assert e.detail["conceding_chair"] == "market"


def test_identical_snapshots_produce_no_entries():
    assert compute_diff(V1, V1) == []


def test_diff_is_deterministic_and_ordered():
    a, b = compute_diff(V1, V2), compute_diff(V1, V2)
    assert types_of(a) == types_of(b)


def test_causal_sentence_renders_a_single_chain_not_a_list():
    """PRD §16.8: 'renders the causal chain as a single sentence path, not a
    list of unrelated changes.'"""
    sentence = causal_sentence(compute_diff(V1, V2))
    assert sentence.count("\n") == 0
    for fragment in ("pricing_wtp", "uncertain", "refuted", "499", "249",
                     "38", "19", "PROCEED", "PIVOT"):
        assert fragment in sentence, fragment


def test_causal_sentence_is_empty_when_nothing_changed():
    assert causal_sentence([]) == ""


def test_causal_sentence_survives_a_partial_chain():
    """Only a verdict change, no parameter or breakpoint movement."""
    v2 = {**V1, "verdict": "STOP"}
    sentence = causal_sentence(compute_diff(V1, v2))
    assert "PROCEED" in sentence and "STOP" in sentence


def test_causal_sentence_leads_cleanly_with_a_parameter_change():
    """No assumption_status_change precedes the parameter move: the sentence
    must not start mid-clause with a dangling 'which', and must not mangle
    the snake_case variable name's casing."""
    v1 = {**V1, "assumptions": {}}
    v2 = {**V2, "assumptions": {}, "breakpoints": V1["breakpoints"],
          "confidence": V1["confidence"], "verdict": V1["verdict"]}
    sentence = causal_sentence(compute_diff(v1, v2))
    assert not sentence.lower().startswith("which")
    assert "price_monthly" in sentence          # not "Price_monthly"


def test_causal_sentence_leads_cleanly_with_a_breakpoint_change():
    """No status or parameter change precedes the breakpoint move: the
    sentence must not start mid-clause with a dangling 'which'."""
    v1 = {**V1, "assumptions": {}, "parameters": {}}
    v2 = {**V2, "assumptions": {}, "parameters": {},
          "confidence": V1["confidence"], "verdict": V1["verdict"]}
    sentence = causal_sentence(compute_diff(v1, v2))
    assert not sentence.lower().startswith("which")
    assert sentence[0].isupper()
