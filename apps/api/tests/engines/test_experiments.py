import pytest

from jury.engines.experiments import generate_experiments
from jury.schemas.economics import SensitivityEntry
from jury.schemas.enums import ExperimentMethod, Provenance


def s(variable, elasticity, provenance="founder_asserted") -> SensitivityEntry:
    return SensitivityEntry(variable=variable, elasticity=elasticity,
                            provenance=Provenance(provenance))


MAP = {"price_monthly": "a-price", "delivery_cost": "a-delivery",
       "take_rate": "a-take", "cac": "a-cac", "churn_monthly": "a-churn",
       "aov": "a-aov"}


def test_evidence_backed_parameters_are_excluded():
    """PRD §16.6: filter provenance = 'founder_asserted'. There is nothing to
    learn about a parameter that already has evidence."""
    out = generate_experiments([s("aov", 9.0, "evidence_backed"),
                                s("price_monthly", 1.0)], MAP)
    assert [e.target_variable for e in out] == ["price_monthly"]


def test_highest_sensitivity_guess_becomes_experiment_one():
    out = generate_experiments([s("delivery_cost", 0.4), s("price_monthly", 3.0)], MAP)
    assert out[0].target_variable == "price_monthly"
    assert out[0].priority == 1


def test_priority_is_dense_and_starts_at_one():
    out = generate_experiments([s("price_monthly", 3.0), s("delivery_cost", 2.0),
                                s("cac", 1.0)], MAP)
    assert [e.priority for e in out] == [1, 2, 3]


def test_top_k_is_respected():
    entries = [s(v, float(9 - i)) for i, v in enumerate(MAP)]
    assert len(generate_experiments(entries, MAP, top_k=3)) == 3


def test_every_experiment_has_a_non_null_kill_criterion():
    """P9: required before the plan can be exported."""
    out = generate_experiments([s("price_monthly", 2.0), s("delivery_cost", 1.0)], MAP)
    assert out and all(e.kill_criterion and e.criterion_spec for e in out)


def test_criterion_spec_is_machine_evaluable():
    out = generate_experiments([s("price_monthly", 2.0)], MAP)
    spec = out[0].criterion_spec
    assert spec.metric and spec.comparator and spec.threshold is not None


def test_price_maps_to_presale_or_fake_door():
    """PRD §16.6 variable-to-method table."""
    out = generate_experiments([s("price_monthly", 2.0)], MAP)
    assert out[0].method in (ExperimentMethod.PRESALE, ExperimentMethod.FAKE_DOOR)


def test_delivery_cost_maps_to_supplier_quote_and_is_free():
    out = generate_experiments([s("delivery_cost", 2.0)], MAP)
    assert out[0].method is ExperimentMethod.SUPPLIER_QUOTE
    assert out[0].est_cost == 0


def test_take_rate_maps_to_interview_script():
    out = generate_experiments([s("take_rate", 2.0)], MAP)
    assert out[0].method is ExperimentMethod.INTERVIEW_SCRIPT


def test_cac_maps_to_landing_ctr():
    out = generate_experiments([s("cac", 2.0)], MAP)
    assert out[0].method is ExperimentMethod.LANDING_CTR


def test_retention_maps_to_a_documented_proxy_with_a_stated_limitation():
    """Spec §26.6: no 30-day experiment measures retention honestly, and the
    product must state that rather than paper over it."""
    out = generate_experiments([s("churn_monthly", 2.0)], MAP)
    assert out[0].method is ExperimentMethod.DOCUMENTED_PROXY
    assert out[0].limitation and "retention" in out[0].limitation.lower()


def test_every_experiment_has_cost_and_duration():
    out = generate_experiments([s(v, 1.0) for v in MAP], MAP)
    assert all(e.est_days is not None and e.est_cost is not None for e in out)


def test_variables_without_a_mapped_assumption_are_skipped():
    out = generate_experiments([s("orphan_variable", 5.0), s("price_monthly", 1.0)], MAP)
    assert [e.target_variable for e in out] == ["price_monthly"]


def test_unmapped_variable_class_is_skipped_rather_than_guessed():
    out = generate_experiments([s("mystery", 5.0)], {"mystery": "a-x"})
    assert out == []


def test_generation_is_deterministic():
    entries = [s("price_monthly", 2.0), s("delivery_cost", 2.0)]
    a = generate_experiments(entries, MAP)
    b = generate_experiments(entries, MAP)
    assert [x.model_dump() for x in a] == [x.model_dump() for x in b]


def test_instructions_are_substantive_not_a_placeholder():
    out = generate_experiments([s("price_monthly", 2.0)], MAP)
    assert len(out[0].instructions) >= 40
    assert "TODO" not in out[0].instructions
