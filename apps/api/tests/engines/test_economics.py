import pytest

from jury.engines.economics.solver import solve
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


def test_no_llm_is_reachable_from_the_economics_engine():
    """P8: economics is computed, not described. Guard the import boundary."""
    import inspect

    from jury.engines.economics import solver, templates
    for mod in (solver, templates):
        src = inspect.getsource(mod)
        for banned in ("litellm", "openai", "groq", "completion(", "jury.llm"):
            assert banned not in src, f"{mod.__name__} references {banned}"
