"""Task 6.3. jury/engines/affected.py."""
from jury.engines.affected import affected_closure

BINDINGS = {"price_monthly": "a-price", "delivery_cost": "a-delivery"}
SENS = [{"variable": "price_monthly", "elasticity": 3.0},
        {"variable": "delivery_cost", "elasticity": 1.0}]


def test_a_changed_assumption_includes_itself():
    got = affected_closure("a-price", parameter_bindings=BINDINGS, sensitivity=SENS)
    assert "a-price" in got.assumptions


def test_a_parameter_bound_to_the_changed_assumption_is_affected():
    got = affected_closure("a-price", parameter_bindings=BINDINGS, sensitivity=SENS)
    assert got.parameters == {"price_monthly"}


def test_unrelated_parameters_are_not_recomputed():
    got = affected_closure("a-price", parameter_bindings=BINDINGS, sensitivity=SENS)
    assert "delivery_cost" not in got.parameters


def test_economics_is_recomputed_when_a_parameter_moved():
    """A parameter change moves every breakpoint, so the solve must re-run."""
    got = affected_closure("a-price", parameter_bindings=BINDINGS, sensitivity=SENS)
    assert got.recompute_economics is True


def test_the_verdict_is_always_recomputed():
    """Confidence depends on every assumption's status, so it always moves."""
    got = affected_closure("a-orphan", parameter_bindings=BINDINGS, sensitivity=SENS)
    assert got.recompute_verdict is True


def test_an_assumption_bound_to_no_parameter_skips_the_economics_solve():
    got = affected_closure("a-orphan", parameter_bindings=BINDINGS, sensitivity=SENS)
    assert got.parameters == set() and got.recompute_economics is False


def test_the_closure_is_deterministic():
    a = affected_closure("a-price", parameter_bindings=BINDINGS, sensitivity=SENS)
    b = affected_closure("a-price", parameter_bindings=BINDINGS, sensitivity=SENS)
    assert a == b


def test_multiple_parameters_bound_to_one_assumption_are_all_included():
    bindings = {"price_monthly": "a-price", "wtp_annual": "a-price"}
    got = affected_closure("a-price", parameter_bindings=bindings, sensitivity=SENS)
    assert got.parameters == {"price_monthly", "wtp_annual"}
