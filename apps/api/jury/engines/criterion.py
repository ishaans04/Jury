"""Kill-criterion evaluation. P9.

Pre-registering the threshold is what stops the founder returning with an
ambiguous result and rationalising it, and it makes the ledger update mechanical
rather than another model judgement (PRD §16.6).
"""
import operator

from jury.schemas.enums import Comparator
from jury.schemas.experiment import CriterionSpec

_OPS = {
    Comparator.GTE: operator.ge,
    Comparator.GT: operator.gt,
    Comparator.LTE: operator.le,
    Comparator.LT: operator.lt,
    Comparator.EQ: operator.eq,
}


def evaluate_criterion(spec: CriterionSpec, result_value: float) -> bool:
    """True if the observed value passes the pre-registered criterion."""
    return bool(_OPS[spec.comparator](result_value, spec.threshold))


def status_for_result(spec: CriterionSpec, result_value: float) -> str:
    """Map a logged result onto experiments.status. No judgement involved."""
    return "passed" if evaluate_criterion(spec, result_value) else "failed"
