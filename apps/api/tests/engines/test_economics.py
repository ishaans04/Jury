import pytest

from jury.engines.economics.solver import find_viable_adjacent, solve
from jury.engines.economics.templates import TEMPLATES
from jury.schemas.economics import Parameter
from jury.schemas.enums import Provenance


def p(value, unit="INR", provenance="founder_asserted") -> Parameter:
    return Parameter(value=value, unit=unit, provenance=Provenance(provenance))


# A hand-computable marketplace: AOV 1000, take 10%, so revenue/txn = 100.
# Costs: delivery 30, payment fee 2% of AOV = 20, support 10  => total 60.
# Contribution margin = 100 - 60 = 40 per transaction.
MARKETPLACE = {
    "aov": p(1000.0),
    "take_rate": p(0.10, "fraction"),
    "delivery_cost": p(30.0),
    "payment_fee": p(0.02, "fraction"),
    "support_cost_per_txn": p(10.0),
    "cac_buyer": p(400.0),
    "cac_supplier": p(0.0),
    "txn_per_buyer_month": p(2.0, "count"),
    "buyer_churn_monthly": p(0.10, "fraction"),
    "fixed_monthly": p(20000.0),
}


def test_all_four_templates_exist():
    assert set(TEMPLATES) == {"marketplace_v1", "saas_v1", "d2c_v1", "services_v1"}


def test_contribution_margin_matches_hand_computation():
    """PRD §19.2: economics solver must agree EXACTLY with hand-computed fixtures."""
    r = solve("marketplace_v1", MARKETPLACE)
    assert r.outputs.contribution_margin == pytest.approx(40.0)


def test_ltv_matches_hand_computation():
    # lifetime months = 1 / churn = 10 ; txn = 2/mo ; CM = 40
    # LTV = 40 * 2 * 10 = 800
    r = solve("marketplace_v1", MARKETPLACE)
    assert r.outputs.ltv == pytest.approx(800.0)


def test_ltv_cac_matches_hand_computation():
    # LTV 800 / CAC 400 = 2.0
    r = solve("marketplace_v1", MARKETPLACE)
    assert r.outputs.ltv_cac == pytest.approx(2.0)


def test_payback_months_matches_hand_computation():
    # monthly contribution per buyer = 40 * 2 = 80 ; CAC 400 -> 5 months
    r = solve("marketplace_v1", MARKETPLACE)
    assert r.outputs.payback_months == pytest.approx(5.0)


def test_breakeven_volume_matches_hand_computation():
    # fixed 20000 / CM 40 = 500 transactions per month
    r = solve("marketplace_v1", MARKETPLACE)
    assert r.outputs.breakeven_volume_monthly == pytest.approx(500.0)


def test_viable_when_margin_positive_and_ltv_cac_above_one():
    assert solve("marketplace_v1", MARKETPLACE).viable is True


def test_not_viable_when_contribution_margin_is_negative():
    params = MARKETPLACE | {"delivery_cost": p(500.0)}
    r = solve("marketplace_v1", params)
    assert r.outputs.contribution_margin < 0
    assert r.viable is False


def test_not_viable_when_ltv_cac_below_one():
    params = MARKETPLACE | {"cac_buyer": p(5000.0)}
    assert solve("marketplace_v1", params).viable is False


# ── breakpoints: PRD §16.5, brentq ──────────────────────────────────────────
def test_delivery_cost_breakpoint_is_exact():
    """CM = 0 when delivery_cost = 100 - 20 - 10 = 70."""
    r = solve("marketplace_v1", MARKETPLACE)
    bp = {b.variable: b for b in r.breakpoints}
    assert bp["delivery_cost"].threshold == pytest.approx(70.0, abs=1e-6)
    assert bp["delivery_cost"].direction == "above"


def test_breakpoint_carries_a_renderable_sentence():
    """PRD §16.5: output is a sentence like 'the business becomes loss-making
    above Rs 38 delivery cost.'"""
    r = solve("marketplace_v1", MARKETPLACE)
    bp = next(b for b in r.breakpoints if b.variable == "delivery_cost")
    assert "delivery_cost" in bp.sentence or "delivery cost" in bp.sentence.lower()
    assert "70" in bp.sentence


def test_take_rate_breakpoint_is_exact():
    """CM = 0 when aov*take = 60, i.e. take_rate = 0.06."""
    r = solve("marketplace_v1", MARKETPLACE)
    bp = {b.variable: b for b in r.breakpoints}
    assert bp["take_rate"].threshold == pytest.approx(0.06, abs=1e-6)
    assert bp["take_rate"].direction == "below"


def test_no_breakpoint_reported_when_none_exists_in_range():
    """A parameter that cannot flip the sign anywhere in its plausible range
    must not be given a fabricated threshold.

    fixed_monthly appears in neither contribution margin, LTV, nor CAC, so no
    value of it crosses anything. It must be ABSENT, not present with an
    invented number.
    """
    r = solve("marketplace_v1", MARKETPLACE)
    reported = {b.variable for b in r.breakpoints}
    assert "fixed_monthly" not in reported
    assert "delivery_cost" in reported


def test_cac_breakpoints_are_reported_via_the_ltv_cac_objective():
    """CAC parameters do not appear in contribution margin, so they are only
    reachable through the LTV/CAC fallback. They are also among the most
    decision-relevant outputs the model produces -- "you cannot pay more than
    X to acquire a buyer" -- so losing them would gut the result.

    LTV here is 800, so ltv_cac crosses 1 at total CAC 800:
      cac_supplier -> 800 - 400 = 400
      cac_buyer    -> 800 - 0   = 800
    """
    r = solve("marketplace_v1", MARKETPLACE)
    bp = {b.variable: b for b in r.breakpoints}
    assert bp["cac_supplier"].threshold == pytest.approx(400.0, abs=1e-6)
    assert bp["cac_buyer"].threshold == pytest.approx(800.0, abs=1e-6)
    assert bp["cac_supplier"].direction == "above"


def test_breakpoints_are_never_nan_or_infinite():
    import math
    r = solve("marketplace_v1", MARKETPLACE)
    for b in r.breakpoints:
        assert math.isfinite(b.threshold)


# ── sensitivity: PRD §16.5, +/-20% one-at-a-time elasticity ────────────────
def test_sensitivity_is_ranked_descending_by_absolute_elasticity():
    r = solve("marketplace_v1", MARKETPLACE)
    mags = [abs(s.elasticity) for s in r.sensitivity]
    assert mags == sorted(mags, reverse=True)


def test_sensitivity_covers_every_template_parameter():
    r = solve("marketplace_v1", MARKETPLACE)
    assert {s.variable for s in r.sensitivity} == set(MARKETPLACE)


def test_sensitivity_carries_provenance_so_experiments_can_filter_on_it():
    """PRD §16.6: the join that makes four pillars one machine."""
    params = MARKETPLACE | {"aov": p(1000.0, "INR", "evidence_backed")}
    r = solve("marketplace_v1", params)
    aov = next(s for s in r.sensitivity if s.variable == "aov")
    assert aov.provenance is Provenance.EVIDENCE_BACKED
    take = next(s for s in r.sensitivity if s.variable == "take_rate")
    assert take.provenance is Provenance.FOUNDER_ASSERTED


def test_aov_and_take_rate_are_the_most_sensitive_in_this_fixture():
    """Both scale revenue linearly, so they must outrank support cost."""
    r = solve("marketplace_v1", MARKETPLACE)
    top = {s.variable for s in r.sensitivity[:2]}
    assert top == {"aov", "take_rate"}


def test_zero_valued_parameter_does_not_break_elasticity():
    params = MARKETPLACE | {"cac_supplier": p(0.0)}
    r = solve("marketplace_v1", params)
    entry = next(s for s in r.sensitivity if s.variable == "cac_supplier")
    assert entry.elasticity == 0.0


# ── determinism and reproducibility ────────────────────────────────────────
def test_solve_is_deterministic():
    """PRD §11.2 dec. 4: reproducible, diffable results across runs."""
    a = solve("marketplace_v1", MARKETPLACE)
    b = solve("marketplace_v1", MARKETPLACE)
    assert a.outputs.model_dump() == b.outputs.model_dump()
    assert [x.model_dump() for x in a.breakpoints] == [x.model_dump() for x in b.breakpoints]
    assert [x.model_dump() for x in a.sensitivity] == [x.model_dump() for x in b.sensitivity]


def test_missing_parameter_uses_the_template_default_and_marks_it_asserted():
    params = {k: v for k, v in MARKETPLACE.items() if k != "support_cost_per_txn"}
    r = solve("marketplace_v1", params)
    entry = next(s for s in r.sensitivity if s.variable == "support_cost_per_txn")
    assert entry.provenance is Provenance.FOUNDER_ASSERTED


def test_unknown_parameter_is_rejected_not_silently_ignored():
    with pytest.raises(ValueError, match="unknown parameter"):
        solve("marketplace_v1", MARKETPLACE | {"vibes": p(1.0)})


def test_unknown_template_is_rejected():
    with pytest.raises(KeyError):
        solve("nonexistent_v1", MARKETPLACE)


# ── saas template ──────────────────────────────────────────────────────────
SAAS = {
    "price_monthly": p(1000.0),
    "cogs_monthly": p(200.0),
    "cac": p(4000.0),
    "churn_monthly": p(0.05, "fraction"),
    "fixed_monthly": p(50000.0),
}


def test_saas_contribution_and_ltv_match_hand_computation():
    # CM = 1000 - 200 = 800 ; lifetime = 1/0.05 = 20 ; LTV = 16000 ; LTV/CAC = 4
    r = solve("saas_v1", SAAS)
    assert r.outputs.contribution_margin == pytest.approx(800.0)
    assert r.outputs.ltv == pytest.approx(16000.0)
    assert r.outputs.ltv_cac == pytest.approx(4.0)
    assert r.outputs.payback_months == pytest.approx(5.0)
    assert r.viable is True


def test_saas_churn_breakpoint_is_exact():
    """LTV/CAC = 1 when 800/churn = 4000, i.e. churn = 0.2."""
    r = solve("saas_v1", SAAS)
    bp = {b.variable: b for b in r.breakpoints}
    assert bp["churn_monthly"].threshold == pytest.approx(0.20, abs=1e-6)
    assert bp["churn_monthly"].direction == "above"


# ── _bracket_endpoint: bounded nudge must not skip past a near-boundary root ─
def test_bracket_nudge_does_not_report_a_wrong_root_past_a_near_boundary_one():
    """Regression for a review finding: _bracket_endpoint's nudge away from a
    domain singularity must stay small enough that it cannot leap over a
    genuine root sitting close to the boundary and land brentq on a
    different, wrong root instead.

    Adversarial objective (constructed during review): singular at x=0 (like
    ltv_cac's zero-total-CAC sentinel), a genuine root at x=0.0009, and a
    second, unrelated root at x=500000, over the wide range [0, 1e6] -- a
    shape a future, non-monotonic template could produce even though none of
    the four shipped templates do (every parameter here is strictly
    monotonic against each objective, so at most one root ever exists today).

    With the old, unbounded nudge (a step scaled to 1e-9 of the *full range*,
    growing x10 over 8 iterations) the first probe landed at 1e-3 -- already
    past the true root at 0.0009 and inside the positive region between the
    two roots -- so the endpoint sign-check paired that positive value with
    the negative value at the far bound and brentq confidently reported the
    WRONG root, ~500000, as if it were a real business threshold. Verified
    by hand-simulating the old step against this exact objective: it returns
    500000.0.

    With the bounded nudge (1e-12 of the range, growing x10 over 6 steps),
    the first probe lands at 1e-6, still on the same (negative) side of the
    near root as the singularity, so the endpoint sign-check no longer
    manufactures a false bracket around the far root -- verified this
    returns None (no sign change visible to the two-point check, since both
    endpoints land negative). That is the one property this test pins down:
    the wrong root must never come back. A "no breakpoint found" outcome is
    correct and safe here; an invented number is not.
    """
    from jury.engines.economics.solver import _solve_breakpoint
    from jury.engines.economics.templates import ParamSpec, Template

    def adversarial(template, values, name, x):
        if x == 0:
            return float("inf")
        return (x - 0.0009) * (500000.0 - x) / x

    spec = ParamSpec(unit="unit", lo=0.0, hi=1_000_000.0, default=1.0)
    fake_template = Template(key="adversarial_v1", params={"x": spec},
                             compute=lambda v: None, primary_output="x")

    bp = _solve_breakpoint(fake_template, {"x": 1.0}, "x", adversarial, "test_output")

    assert bp is None or bp.threshold != pytest.approx(500000.0, rel=1e-3)


def test_bracket_nudge_still_finds_a_genuine_near_boundary_root():
    """Companion to the test above: confirm the bounded nudge has not traded
    away its original purpose. With the confounding far root removed (hi kept
    well below it), a genuine root sitting close to a domain singularity must
    still be found -- this is the cac_buyer=800 case in miniature.
    """
    from jury.engines.economics.solver import _solve_breakpoint
    from jury.engines.economics.templates import ParamSpec, Template

    def near_root_only(template, values, name, x):
        if x == 0:
            return float("inf")
        return x - 0.0009  # single root at 0.0009, no second root in range

    spec = ParamSpec(unit="unit", lo=0.0, hi=1.0, default=0.5)
    fake_template = Template(key="near_root_v1", params={"x": spec},
                             compute=lambda v: None, primary_output="x")

    bp = _solve_breakpoint(fake_template, {"x": 0.5}, "x", near_root_only, "test_output")

    assert bp is not None
    assert bp.threshold == pytest.approx(0.0009, abs=1e-6)


# ── find_viable_adjacent: PRD §9.4 pivot feasibility ────────────────────────

SAAS_BASE = {
    "price_monthly": p(150.0),                     # founder_asserted
    "cogs_monthly": p(200.0),                       # founder_asserted
    "cac": p(4000.0),
    "churn_monthly": p(0.05, "fraction"),
    "fixed_monthly": p(50000.0),
}


def test_no_adjacent_needed_when_already_viable():
    """A currently-viable config has nothing to pivot to."""
    assert solve("saas_v1", SAAS).viable is True
    assert find_viable_adjacent("saas_v1", SAAS) is False


def test_adjacent_viable_config_found_by_moving_founder_asserted_guesses():
    """price_monthly=150, cogs_monthly=200 -> CM=-50, not viable. Both are
    founder_asserted guesses, so the best-case search may move price up to
    its hi bound and cogs down to its lo bound, which easily clears
    viability. A pivot exists."""
    r = solve("saas_v1", SAAS_BASE)
    assert r.viable is False
    assert find_viable_adjacent("saas_v1", SAAS_BASE) is True


def test_evidence_backed_parameter_is_never_moved_even_to_rescue_viability():
    """cogs_monthly is pinned at a large EVIDENCE_BACKED value (2,000,000) --
    what the world actually shows. Even moving founder_asserted price_monthly
    all the way to its hi bound (1,000,000) cannot clear a fixed cost of
    2,000,000, so no adjacent configuration is viable. If the search moved
    the evidence-backed cogs value instead (down to its lo bound, which
    trivially fixes viability), this would come back True -- it must not."""
    params = SAAS_BASE | {"cogs_monthly": p(2_000_000.0, "INR", "evidence_backed")}
    r = solve("saas_v1", params)
    assert r.viable is False
    assert find_viable_adjacent("saas_v1", params) is False


def test_still_not_viable_even_at_best_case_founder_asserted_values():
    """fixed_monthly does not affect contribution_margin or ltv_cac at all
    (it only affects breakeven volume), so it cannot rescue an unviable
    margin no matter where it is moved. Pin the culprit (cogs) as evidence
    and make price founder_asserted but already at a value that, even pushed
    to its bound, still loses against the pinned cost -- an unreachable
    pivot."""
    params = {
        "price_monthly": p(100.0),                                  # founder_asserted
        "cogs_monthly": p(5_000_000.0, "INR", "evidence_backed"),     # pinned, huge
        "cac": p(4000.0, "INR", "evidence_backed"),
        "churn_monthly": p(0.05, "fraction", "evidence_backed"),
        "fixed_monthly": p(50000.0, "INR", "evidence_backed"),
    }
    r = solve("saas_v1", params)
    assert r.viable is False
    assert find_viable_adjacent("saas_v1", params) is False


def test_no_llm_is_reachable_from_the_economics_engine():
    """P8: economics is computed, not described. Guard the import boundary."""
    import inspect

    from jury.engines.economics import solver, templates
    for mod in (solver, templates):
        src = inspect.getsource(mod)
        for banned in ("litellm", "openai", "groq", "completion(", "jury.llm"):
            assert banned not in src, f"{mod.__name__} references {banned}"
