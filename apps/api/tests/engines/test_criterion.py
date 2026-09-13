import pytest

from jury.engines.criterion import evaluate_criterion, status_for_result
from jury.schemas.experiment import CriterionSpec


def spec(comparator=">=", threshold=4.0, metric="prepay_count", n=20) -> CriterionSpec:
    return CriterionSpec(metric=metric, comparator=comparator,
                         threshold=threshold, n=n)


@pytest.mark.parametrize("comparator,threshold,value,expected", [
    (">=", 4.0, 4.0, True),    (">=", 4.0, 3.9, False),   (">=", 4.0, 5.0, True),
    (">",  4.0, 4.0, False),   (">",  4.0, 4.1, True),
    ("<=", 4.0, 4.0, True),    ("<=", 4.0, 4.1, False),
    ("<",  4.0, 4.0, False),   ("<",  4.0, 3.9, True),
    ("==", 4.0, 4.0, True),    ("==", 4.0, 4.0001, False),
])
def test_every_comparator_evaluates_exactly(comparator, threshold, value, expected):
    """PRD §19.2: kill-criterion evaluation must be 100%."""
    assert evaluate_criterion(spec(comparator, threshold), value) is expected


def test_the_prd_worked_example():
    """PRD §7.10: 3/20 pre-paid against a criterion of >=4/20 -> refuted."""
    s = CriterionSpec(metric="prepay_count", comparator=">=", threshold=4, n=20)
    assert evaluate_criterion(s, 3.0) is False
    assert status_for_result(s, 3.0) == "failed"
    assert status_for_result(s, 4.0) == "passed"


def test_evaluation_is_mechanical_and_repeatable():
    """PRD §16.6: pre-registering the threshold makes the ledger update mechanical
    rather than another model judgement."""
    s = spec()
    for _ in range(50):
        assert evaluate_criterion(s, 3.9999) is False
