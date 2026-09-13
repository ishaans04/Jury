"""Experiment generation. PRD §16.6.

The join that makes the four pillars one machine instead of four features:

    sensitivity ranking
      -> filter provenance = 'founder_asserted'
          -> the highest-sensitivity parameter that is still a guess
              -> is, by construction, the highest-value thing to go learn
                  -> becomes experiment #1
"""
from dataclasses import dataclass

from jury.schemas.economics import SensitivityEntry
from jury.schemas.enums import Comparator, ExperimentMethod, Provenance
from jury.schemas.experiment import CriterionSpec, ExperimentDraft


@dataclass(frozen=True, slots=True)
class MethodSpec:
    method: ExperimentMethod
    instructions: str
    kill_criterion: str
    criterion: CriterionSpec
    est_cost: float
    est_days: int
    limitation: str | None = None
    # Name of the modelled value (from the `modelled` dict passed to
    # generate_experiments) that this method's criterion.threshold must be
    # filled in from. None means the criterion is already self-contained
    # (its threshold is a real, fixed number, not something borrowed from
    # a solved economics model). When set and the caller does not supply a
    # matching value, the experiment is skipped rather than emitted with a
    # placeholder threshold that would always pass or always fail.
    threshold_source: str | None = None


# Prose template for the four methods whose kill criterion depends on a
# modelled value. Applied only once that value is actually available;
# {value:g} is interpolated with the real number so the founder reads a
# concrete line rather than a reference to "the model".
_THRESHOLD_KILL_CRITERIA: dict[str, str] = {
    "delivery_cost": "Median written quote exceeds the modelled break-even delivery cost of {value:g}.",
    "cac": "Measured cost per signup exceeds the modelled CAC of {value:g}.",
    "aov": "Median attempted basket value falls below the asserted AOV of {value:g}.",
    "churn_monthly": (
        "Comparable published churn exceeds the modelled monthly churn of "
        "{value:g}, and no structural reason for a difference is documented."),
}

# PRD §16.6 variable-to-method mapping. Keyed by exact variable name; prefix
# fallbacks below catch families like wtp_*.
#
# Four of these (delivery_cost, cac, aov, churn_monthly) declare
# threshold_source: their criterion has no self-contained number and must be
# filled in from a solved economics model at call time (see
# generate_experiments). Without a matching entry in `modelled`, the
# experiment is skipped rather than emitted with an unsatisfiable or
# trivially-true placeholder threshold -- a criterion that always returns the
# same verdict regardless of the result is worse than no criterion, because
# it looks pre-registered while deciding nothing.
VARIABLE_METHODS: dict[str, MethodSpec] = {
    "price_monthly": MethodSpec(
        method=ExperimentMethod.PRESALE,
        instructions=(
            "Build a one-page offer at the asserted price with a real checkout. "
            "Drive 20 qualified visitors from the channel you actually intend to "
            "use. Count how many complete a pre-payment, not how many say they "
            "would. Refund everyone afterwards."),
        kill_criterion="Fewer than 4 of 20 qualified visitors pre-pay at the asserted price.",
        criterion=CriterionSpec(metric="prepay_count", comparator=Comparator.GTE,
                                threshold=4, n=20),
        est_cost=5000.0, est_days=7),
    "take_rate": MethodSpec(
        method=ExperimentMethod.INTERVIEW_SCRIPT,
        instructions=(
            "Speak to 10 supply-side participants. State the commission as a fact, "
            "not a question, and ask them to commit to a first listing. Record "
            "acceptance before any negotiation, and count only unprompted yeses."),
        kill_criterion="Fewer than 5 of 10 supply-side contacts accept the stated commission.",
        criterion=CriterionSpec(metric="accept_count", comparator=Comparator.GTE,
                                threshold=5, n=10),
        est_cost=0.0, est_days=7),
    "delivery_cost": MethodSpec(
        method=ExperimentMethod.SUPPLIER_QUOTE,
        instructions=(
            "Request written quotes from at least 5 providers for your actual "
            "volume, weight and route. Use the median of the written quotes, not "
            "the cheapest, and keep the emails as your source."),
        kill_criterion="Median written quote exceeds the modelled break-even delivery cost.",
        criterion=CriterionSpec(metric="median_quote", comparator=Comparator.LTE,
                                threshold=0.0, n=5),
        est_cost=0.0, est_days=5, threshold_source="delivery_cost"),
    "cac": MethodSpec(
        method=ExperimentMethod.LANDING_CTR,
        instructions=(
            "Run a landing page against the intended paid channel with a fixed "
            "budget. Measure cost per completed signup, not cost per click, and "
            "run long enough to clear the platform's learning phase."),
        kill_criterion="Measured cost per signup exceeds the modelled CAC.",
        criterion=CriterionSpec(metric="cost_per_signup", comparator=Comparator.LTE,
                                threshold=0.0, n=None),
        est_cost=10000.0, est_days=14, threshold_source="cac"),
    "aov": MethodSpec(
        method=ExperimentMethod.FAKE_DOOR,
        instructions=(
            "Publish the real basket at the assumed average order value with a "
            "working cart. Measure completed checkout attempts and the actual "
            "basket value distribution across at least 30 sessions."),
        kill_criterion="Median attempted basket value falls below the asserted AOV.",
        criterion=CriterionSpec(metric="median_basket", comparator=Comparator.GTE,
                                threshold=0.0, n=30),
        est_cost=5000.0, est_days=10, threshold_source="aov"),
    "churn_monthly": MethodSpec(
        method=ExperimentMethod.DOCUMENTED_PROXY,
        instructions=(
            "Retention cannot be measured honestly inside 30 days. Substitute a "
            "documented proxy: published churn or review-attrition figures for the "
            "two closest comparable products, cited by URL. Record the proxy and "
            "the gap between proxy and your own case."),
        kill_criterion=(
            "Comparable published churn exceeds the modelled monthly churn, and no "
            "structural reason for a difference is documented."),
        criterion=CriterionSpec(metric="comparable_churn_monthly",
                                comparator=Comparator.LTE, threshold=0.0, n=2),
        est_cost=0.0, est_days=3, threshold_source="churn_monthly",
        limitation=(
            "No 30-day experiment can measure retention honestly. This is a "
            "documented proxy, not a measurement, and the verdict treats it as such.")),
    "regulatory_permitted": MethodSpec(
        method=ExperimentMethod.REGISTRY_CHECK,
        instructions=(
            "Identify the governing regulator and search its public register for "
            "the licence or registration your model requires. If the register is "
            "ambiguous, send a written enquiry and keep the reference number."),
        kill_criterion="The activity requires a licence you cannot obtain within 90 days.",
        criterion=CriterionSpec(metric="licence_obtainable_days",
                                comparator=Comparator.LTE, threshold=90, n=None),
        est_cost=0.0, est_days=21),
}

# Variable families that share a method with a canonical variable above.
_PREFIX_ALIASES: tuple[tuple[str, str], ...] = (
    ("wtp_", "price_monthly"),
    ("price", "price_monthly"),
    ("cac_", "cac"),
    ("churn", "churn_monthly"),
    ("retention", "churn_monthly"),
    ("cost_per", "delivery_cost"),
    ("fulfilment", "delivery_cost"),
    ("cogs", "delivery_cost"),
)


def _method_for(variable: str) -> MethodSpec | None:
    if variable in VARIABLE_METHODS:
        return VARIABLE_METHODS[variable]
    v = variable.lower()
    for prefix, canonical in _PREFIX_ALIASES:
        if v.startswith(prefix):
            return VARIABLE_METHODS[canonical]
    return None       # unmapped: skip rather than invent a method


def generate_experiments(
    sensitivity: list[SensitivityEntry],
    assumption_for_variable: dict[str, str],
    top_k: int = 5,
    modelled: dict[str, float] | None = None,
) -> list[ExperimentDraft]:
    """Top-k founder-asserted, highest-sensitivity parameters, as experiments (F13).

    Every returned draft carries a non-null kill criterion and a machine-evaluable
    criterion_spec (P9).

    `modelled` supplies the real, solved economics values (break-even delivery
    cost, CAC, AOV, monthly churn) that four of the methods need to make their
    criterion honest. A method whose spec declares `threshold_source` and
    finds no matching entry in `modelled` is skipped entirely rather than
    emitted with a placeholder threshold: a criterion that always passes or
    always fails regardless of the result is worse than a missing one, since
    it looks pre-registered while deciding nothing. Priority stays dense
    across such a skip, exactly as it already does across an unmapped
    variable.
    """
    guesses = [s for s in sensitivity if s.provenance is Provenance.FOUNDER_ASSERTED]
    guesses.sort(key=lambda s: (-abs(s.elasticity), s.variable))
    modelled = modelled or {}

    drafts: list[ExperimentDraft] = []
    for entry in guesses:
        if len(drafts) >= top_k:
            break
        assumption_id = assumption_for_variable.get(entry.variable)
        if assumption_id is None:
            continue
        spec = _method_for(entry.variable)
        if spec is None:
            continue

        criterion = spec.criterion
        kill_criterion = spec.kill_criterion
        if spec.threshold_source is not None:
            if spec.threshold_source not in modelled:
                continue     # no modelled value: an honest absence, not a guess
            value = modelled[spec.threshold_source]
            criterion = criterion.model_copy(update={"threshold": value})
            kill_criterion = _THRESHOLD_KILL_CRITERIA[spec.threshold_source].format(
                value=value)

        drafts.append(ExperimentDraft(
            assumption_id=assumption_id,
            target_variable=entry.variable,
            method=spec.method,
            instructions=spec.instructions,
            kill_criterion=kill_criterion,
            criterion_spec=criterion,
            est_cost=spec.est_cost,
            est_days=spec.est_days,
            priority=len(drafts) + 1,
            limitation=spec.limitation,
        ))
    return drafts
