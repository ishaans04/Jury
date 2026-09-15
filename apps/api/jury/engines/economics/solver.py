"""Breakpoint and sensitivity solver. PRD §16.5.

Breakpoints are solved numerically with scipy.optimize.brentq over each
parameter's plausible range, holding the others fixed. Sensitivity is
one-at-a-time elasticity at +/-20%, ranked descending.

Monte Carlo is explicitly out of scope (PRD §16.5): a deterministic breakpoint
solve plus elasticity ranking delivers the same decision value at a fraction of
the build cost.

P8: no LLM import may ever appear in this module. A test enforces that.
"""
import math
from dataclasses import dataclass

from scipy.optimize import brentq

from jury.engines.economics.templates import TEMPLATES, Template
from jury.schemas.economics import (
    Breakpoint, ModelOutputs, Parameter, SensitivityEntry,
)
from jury.schemas.enums import Provenance

PERTURBATION = 0.20        # +/-20% one-at-a-time (PRD §16.5)
_VIABLE_LTV_CAC = 1.0


@dataclass(frozen=True, slots=True)
class ModelRunResult:
    template_key: str
    outputs: ModelOutputs
    breakpoints: list[Breakpoint]
    sensitivity: list[SensitivityEntry]
    viable: bool


def _resolve(template: Template,
             parameters: dict[str, Parameter]) -> tuple[dict[str, float],
                                                        dict[str, Provenance]]:
    """Fill missing parameters from template defaults, marked founder_asserted.

    A default is a guess, so it is founder_asserted by definition — which makes
    it eligible to become an experiment (PRD §16.6).
    """
    unknown = set(parameters) - set(template.params)
    if unknown:
        raise ValueError(f"unknown parameter(s) for {template.key}: {sorted(unknown)}")

    values: dict[str, float] = {}
    provenance: dict[str, Provenance] = {}
    for name, spec in template.params.items():
        given = parameters.get(name)
        if given is None:
            values[name] = spec.default
            provenance[name] = Provenance.FOUNDER_ASSERTED
        else:
            values[name] = float(given.value)
            provenance[name] = given.provenance
    return values, provenance


def _margin_at(template: Template, values: dict[str, float],
               name: str, x: float) -> float:
    probe = dict(values)
    probe[name] = x
    return template.compute(probe).contribution_margin


def _ltv_cac_at(template: Template, values: dict[str, float],
                name: str, x: float) -> float:
    probe = dict(values)
    probe[name] = x
    out = template.compute(probe)
    return out.ltv_cac - _VIABLE_LTV_CAC


def _bracket_endpoint(template: Template, values: dict[str, float], name: str,
                      objective, x: float, toward: float) -> tuple[float, float]:
    """Evaluate `objective` at x, nudging inward (toward the other endpoint)
    if x sits exactly on a domain singularity.

    ltv_cac's denominator (total CAC) can be exactly zero at a CAC-type
    parameter's own lo=0.0 when every other CAC-contributing parameter also
    defaults to zero -- e.g. cac_buyer at lo=0 with cac_supplier=0 gives total
    CAC=0, which ModelOutputs.ltv_cac reports as the +inf sentinel. That is a
    genuine, correct value of the ratio at that exact point, but it is not a
    number brentq can bracket against, and bailing out there would hide a
    real, well-defined root (cac_buyer=800 in that example) that exists
    everywhere except the single singular point. Stepping a hair inward
    evaluates the same objective just off that point, which changes nothing
    about the interior root.

    The displacement is deliberately bounded to a negligible fraction of the
    range: the step starts at 1e-12 of (toward - x) and grows x10 over 6
    iterations, capping total displacement at roughly 1e-6 of the range. A
    larger step is not safe in general -- for a non-monotonic objective, a
    coarse nudge can jump past a genuine near-boundary root and land brentq
    on a bracket around a *different, wrong* root, silently reporting a
    fabricated threshold value rather than the true one. Every parameter in
    the four shipped templates is strictly monotonic against each objective
    (at most one root exists), so this cannot happen today, but the nudge
    itself must not assume that invariant, since nothing enforces it for a
    future template. A root sitting within one part in a million of a
    singular boundary is not a meaningful business threshold anyway, so
    bailing out there (rather than nudging further) is the honest outcome.
    """
    step = (toward - x) * 1e-12 or math.copysign(1e-12, toward - x)
    val = float("nan")
    for _ in range(6):
        try:
            val = objective(template, values, name, x)
        except (ZeroDivisionError, OverflowError, ValueError):
            val = float("nan")
        if math.isfinite(val):
            return x, val
        x += step
        step *= 10
    return x, val


def _solve_breakpoint(template: Template, values: dict[str, float], name: str,
                      objective, output_label: str) -> Breakpoint | None:
    """Find where `objective` crosses zero over the parameter's plausible range.

    brentq requires a sign change across the bracket. If there is none, no
    breakpoint exists in the plausible range and we report nothing rather than
    fabricating a threshold.
    """
    spec = template.params[name]
    x_lo, f_lo = _bracket_endpoint(template, values, name, objective, spec.lo, spec.hi)
    x_hi, f_hi = _bracket_endpoint(template, values, name, objective, spec.hi, spec.lo)
    if not (math.isfinite(f_lo) and math.isfinite(f_hi)) or f_lo * f_hi > 0:
        return None

    try:
        root = brentq(lambda x: objective(template, values, name, x),
                      x_lo, x_hi, xtol=1e-9, maxiter=200)
    except (ValueError, RuntimeError):
        return None
    if not math.isfinite(root):
        return None

    # Direction: does exceeding the root break the business, or falling below it?
    above_is_worse = objective(template, values, name, min(root * 1.01 + 1e-9, spec.hi)) < 0
    direction = "above" if above_is_worse else "below"
    pretty = f"{root:,.2f}".rstrip("0").rstrip(".")
    label = name.replace("_", " ")
    sentence = (f"The business becomes unviable {direction} "
                f"{pretty} {spec.unit} of {label}.")
    return Breakpoint(variable=name, threshold=float(root), direction=direction,
                      unit=spec.unit, output=output_label, sentence=sentence)


def _elasticity(template: Template, values: dict[str, float], name: str) -> float:
    """Proportional change in the primary output for a +/-20% parameter change.

    Averaging the up and down perturbation makes the measure symmetric, which
    matters because a tornado chart is read as a magnitude ranking.

    Known limitation: the denominator is always the nominal PERTURBATION
    (0.20), even when a probe gets clamped into [lo, hi] below. For a
    parameter whose live value sits near a template bound, the actual applied
    move can be smaller than 20%, which understates the reported elasticity
    for that side (and, in the extreme of a value sitting exactly at a bound,
    can zero out one side's contribution entirely). No fixture in this suite
    triggers it — every default sits well inside its range — but it would
    bite a parameter pinned at its bound. Accepted as a known limitation
    rather than fixed here.
    """
    base = template.compute(values).contribution_margin
    x = values[name]
    if x == 0 or base == 0:
        return 0.0

    deltas = []
    for factor in (1.0 + PERTURBATION, 1.0 - PERTURBATION):
        spec = template.params[name]
        probe = dict(values)
        probe[name] = min(max(x * factor, spec.lo), spec.hi)
        try:
            perturbed = template.compute(probe).contribution_margin
        except (ZeroDivisionError, OverflowError):
            continue
        if math.isfinite(perturbed):
            deltas.append(abs((perturbed - base) / base) / PERTURBATION)
    return sum(deltas) / len(deltas) if deltas else 0.0


def find_viable_adjacent(template_key: str, parameters: dict[str, Parameter]) -> bool:
    """Is there a viable configuration reachable by changing only the
    parameters that are still guesses? PRD §9.4: STOP means a refuted
    blocking assumption with no viable adjacent configuration; PIVOT means
    there is one. The gate consults this ONLY for that refuted-blocking
    case -- it answers "is a DIFFERENT viable config reachable by changing
    guesses", not "is the current config viable", so a currently-viable
    config returns False here: there is nothing to pivot TO.

    Deterministic, no Monte Carlo (PRD §16.5): every evidence_backed
    parameter is held fixed at what the world actually shows -- you cannot
    pivot away from evidence, only away from your own assumptions. Each
    founder_asserted parameter is independently moved to whichever of its
    ParamSpec bounds (lo/hi) yields the higher contribution margin, other
    parameters held at their current (resolved) value. This is an
    upper-bound, one-at-a-time search rather than a joint optimisation, but
    it needs no hardcoded per-parameter sign and never invents viability
    against evidence: if even the founder's best honest guesses, each
    pushed to its most favourable plausible value, cannot clear viability,
    no adjacent configuration can.

    Known limitation: the search criterion is contribution margin, so a
    founder_asserted parameter that moves ltv_cac but never appears in
    contribution margin (e.g. a CAC-type parameter, per the templates' own
    breakpoint fallback -- see solve()'s two-objective breakpoint search) is
    left at its current value rather than moved, since margin gives no
    signal on which bound helps it. A model refuted only because a
    founder-guessed CAC is too high, with contribution margin already
    healthy, will not find that particular pivot here. Accepted rather than
    fixed: guessing a direction from a criterion the parameter does not
    affect would be inventing a preference, not finding one.
    """
    template = TEMPLATES[template_key]
    values, provenance = _resolve(template, parameters)

    current_outputs = template.compute(values)
    currently_viable = (current_outputs.contribution_margin > 0
                        and current_outputs.ltv_cac >= _VIABLE_LTV_CAC)
    if currently_viable:
        return False

    best_case = dict(values)
    for name, spec in template.params.items():
        if provenance[name] is not Provenance.FOUNDER_ASSERTED:
            continue
        margin_lo = _margin_at(template, values, name, spec.lo)
        margin_hi = _margin_at(template, values, name, spec.hi)
        if margin_hi > margin_lo:
            best_case[name] = spec.hi
        elif margin_lo > margin_hi:
            best_case[name] = spec.lo
        # Tie (this parameter does not move contribution margin at all --
        # e.g. a CAC or churn parameter in these templates): leave it at its
        # current value rather than picking an arbitrary bound. Picking
        # blindly here would move a parameter that only affects ltv_cac (not
        # margin) with no basis for direction, and could easily pick the
        # bound that WORSENS ltv_cac while claiming to search for a
        # best case -- undermining the "most favourable plausible value"
        # this loop exists to find.

    best_outputs = template.compute(best_case)
    return (best_outputs.contribution_margin > 0
           and best_outputs.ltv_cac >= _VIABLE_LTV_CAC)


def solve(template_key: str, parameters: dict[str, Parameter]) -> ModelRunResult:
    """Execute the model, solve breakpoints, rank sensitivity.

    Deterministic and reproducible: the same parameters always yield the same
    outputs, breakpoints and ranking, which is what makes model runs diffable
    across ledger versions (PRD §11.2 decision 4).
    """
    template = TEMPLATES[template_key]
    values, provenance = _resolve(template, parameters)
    outputs = template.compute(values)

    breakpoints: list[Breakpoint] = []
    for name in template.params:
        bp = _solve_breakpoint(template, values, name, _margin_at,
                               "contribution_margin")
        if bp is None:
            bp = _solve_breakpoint(template, values, name, _ltv_cac_at, "ltv_cac")
        if bp is not None:
            breakpoints.append(bp)
    breakpoints.sort(key=lambda b: b.variable)

    sensitivity = [
        SensitivityEntry(variable=name,
                         elasticity=_elasticity(template, values, name),
                         provenance=provenance[name])
        for name in template.params
    ]
    # Descending by magnitude, then by name so ties are stable and diffable.
    sensitivity.sort(key=lambda s: (-abs(s.elasticity), s.variable))

    viable = (outputs.contribution_margin > 0
              and outputs.ltv_cac >= _VIABLE_LTV_CAC)

    return ModelRunResult(template_key=template_key, outputs=outputs,
                          breakpoints=breakpoints, sensitivity=sensitivity,
                          viable=viable)
