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


def _solve_breakpoint(template: Template, values: dict[str, float], name: str,
                      objective, output_label: str) -> Breakpoint | None:
    """Find where `objective` crosses zero over the parameter's plausible range.

    brentq requires a sign change across the bracket. If there is none, no
    breakpoint exists in the plausible range and we report nothing rather than
    fabricating a threshold.
    """
    spec = template.params[name]
    try:
        f_lo = objective(template, values, name, spec.lo)
        f_hi = objective(template, values, name, spec.hi)
    except (ZeroDivisionError, OverflowError, ValueError):
        return None
    if not (math.isfinite(f_lo) and math.isfinite(f_hi)) or f_lo * f_hi > 0:
        return None

    try:
        root = brentq(lambda x: objective(template, values, name, x),
                      spec.lo, spec.hi, xtol=1e-9, maxiter=200)
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


def _affects_ltv(template: Template, values: dict[str, float], name: str) -> bool:
    """True if flexing this parameter across its range changes LTV itself.

    Distinguishes a genuine LTV-driven breakpoint (churn, via the lifetime
    multiplier) from a parameter that only appears as an additive term in the
    ltv_cac ratio's own denominator (a CAC component). The latter always has a
    *trivial* root at cac == ltv regardless of which CAC sub-component is
    flexed — every such parameter would "break" the business past some value
    by construction, which is not a discovered economic mechanism, it is the
    tautology that CAC must not exceed LTV. Gating the fallback on this keeps
    "no breakpoint exists" true for parameters like cac_supplier that the
    contribution-margin objective already correctly found nothing for.
    """
    spec = template.params[name]
    probe_lo = dict(values); probe_lo[name] = spec.lo
    probe_hi = dict(values); probe_hi[name] = spec.hi
    try:
        ltv_lo = template.compute(probe_lo).ltv
        ltv_hi = template.compute(probe_hi).ltv
    except (ZeroDivisionError, OverflowError, ValueError):
        return True   # can't establish independence; don't suppress on error
    if not (math.isfinite(ltv_lo) and math.isfinite(ltv_hi)):
        return True
    return not math.isclose(ltv_lo, ltv_hi, rel_tol=1e-9, abs_tol=1e-9)


def _elasticity(template: Template, values: dict[str, float], name: str) -> float:
    """Proportional change in the primary output for a +/-20% parameter change.

    Averaging the up and down perturbation makes the measure symmetric, which
    matters because a tornado chart is read as a magnitude ranking.
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
        if bp is None and _affects_ltv(template, values, name):
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
