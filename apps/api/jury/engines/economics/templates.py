"""Typed economics templates. PRD §16.5 and §11.2 decision 4.

"Templates, not generated code." The LLM fills a validated parameter schema; it
never authors or executes code. This buys reproducible, diffable results across
runs, a provenance field per parameter so sensitivity can mechanically nominate
the next experiment, and elimination of the untrusted-code-execution surface.

P8: no LLM import may ever appear in this module. A test enforces that.
"""
from collections.abc import Callable
from dataclasses import dataclass

from jury.schemas.economics import ModelOutputs


@dataclass(frozen=True, slots=True)
class ParamSpec:
    unit: str
    lo: float           # lower bound of the plausible range, for brentq
    hi: float           # upper bound
    default: float


@dataclass(frozen=True, slots=True)
class Template:
    key: str
    params: dict[str, ParamSpec]
    compute: Callable[[dict[str, float]], ModelOutputs]
    primary_output: str


def _finite_lifetime(churn: float) -> float:
    """Expected lifetime in months. Guard churn=0 so LTV stays finite."""
    return 1.0 / churn if churn > 1e-9 else 1e6


def _assemble(cm: float, txn_per_month: float, churn: float, cac: float,
              fixed_monthly: float) -> ModelOutputs:
    """Shared output assembly so every template reports the same five numbers."""
    lifetime = _finite_lifetime(churn)
    ltv = cm * txn_per_month * lifetime
    monthly_contribution = cm * txn_per_month
    return ModelOutputs(
        contribution_margin=cm,
        ltv=ltv,
        ltv_cac=(ltv / cac) if cac > 0 else float("inf"),
        payback_months=(cac / monthly_contribution) if monthly_contribution > 0 else None,
        breakeven_volume_monthly=(fixed_monthly / cm) if cm > 0 else None,
    )


# ── marketplace ─────────────────────────────────────────────────────────────
def _marketplace(v: dict[str, float]) -> ModelOutputs:
    revenue_per_txn = v["aov"] * v["take_rate"]
    cost_per_txn = (v["delivery_cost"]
                    + v["aov"] * v["payment_fee"]
                    + v["support_cost_per_txn"])
    cm = revenue_per_txn - cost_per_txn
    cac = v["cac_buyer"] + v["cac_supplier"]
    return _assemble(cm, v["txn_per_buyer_month"], v["buyer_churn_monthly"],
                     cac, v["fixed_monthly"])


# ── subscription saas ───────────────────────────────────────────────────────
def _saas(v: dict[str, float]) -> ModelOutputs:
    cm = v["price_monthly"] - v["cogs_monthly"]
    return _assemble(cm, 1.0, v["churn_monthly"], v["cac"], v["fixed_monthly"])


# ── d2c ─────────────────────────────────────────────────────────────────────
def _d2c(v: dict[str, float]) -> ModelOutputs:
    gross = v["price"] - v["cogs"] - v["fulfilment_cost"]
    cm = gross * (1.0 - v["return_rate"])
    return _assemble(cm, v["orders_per_customer_month"], v["churn_monthly"],
                     v["cac"], v["fixed_monthly"])


# ── services ────────────────────────────────────────────────────────────────
def _services(v: dict[str, float]) -> ModelOutputs:
    billable = v["hours_per_month"] * v["utilisation"]
    cm = billable * (v["rate_hourly"] - v["delivery_cost_hourly"])
    return _assemble(cm, 1.0, v["client_churn_monthly"], v["cac"], v["fixed_monthly"])


TEMPLATES: dict[str, Template] = {
    "marketplace_v1": Template(
        key="marketplace_v1",
        primary_output="contribution_margin",
        compute=_marketplace,
        params={
            "aov":                 ParamSpec("currency", 1.0, 1_000_000.0, 1000.0),
            "take_rate":           ParamSpec("fraction", 0.0001, 0.95, 0.10),
            "delivery_cost":       ParamSpec("currency_per_txn", 0.0, 1_000_000.0, 30.0),
            "payment_fee":         ParamSpec("fraction", 0.0, 0.30, 0.02),
            "support_cost_per_txn":ParamSpec("currency_per_txn", 0.0, 1_000_000.0, 10.0),
            "cac_buyer":           ParamSpec("currency", 0.0, 1_000_000.0, 400.0),
            "cac_supplier":        ParamSpec("currency", 0.0, 1_000_000.0, 0.0),
            "txn_per_buyer_month": ParamSpec("count", 0.01, 1000.0, 2.0),
            "buyer_churn_monthly": ParamSpec("fraction", 0.0001, 0.99, 0.10),
            "fixed_monthly":       ParamSpec("currency", 0.0, 100_000_000.0, 20000.0),
        },
    ),
    "saas_v1": Template(
        key="saas_v1",
        primary_output="contribution_margin",
        compute=_saas,
        params={
            "price_monthly": ParamSpec("currency_per_month", 1.0, 1_000_000.0, 1000.0),
            "cogs_monthly":  ParamSpec("currency_per_month", 0.0, 1_000_000.0, 200.0),
            "cac":           ParamSpec("currency", 0.0, 10_000_000.0, 4000.0),
            "churn_monthly": ParamSpec("fraction", 0.0001, 0.99, 0.05),
            "fixed_monthly": ParamSpec("currency", 0.0, 100_000_000.0, 50000.0),
        },
    ),
    "d2c_v1": Template(
        key="d2c_v1",
        primary_output="contribution_margin",
        compute=_d2c,
        params={
            "price":                     ParamSpec("currency", 1.0, 1_000_000.0, 1200.0),
            "cogs":                      ParamSpec("currency", 0.0, 1_000_000.0, 400.0),
            "fulfilment_cost":           ParamSpec("currency", 0.0, 1_000_000.0, 120.0),
            "return_rate":               ParamSpec("fraction", 0.0, 0.9, 0.08),
            "cac":                       ParamSpec("currency", 0.0, 1_000_000.0, 600.0),
            "orders_per_customer_month": ParamSpec("count", 0.01, 100.0, 0.5),
            "churn_monthly":             ParamSpec("fraction", 0.0001, 0.99, 0.20),
            "fixed_monthly":             ParamSpec("currency", 0.0, 100_000_000.0, 30000.0),
        },
    ),
    "services_v1": Template(
        key="services_v1",
        primary_output="contribution_margin",
        compute=_services,
        params={
            "rate_hourly":          ParamSpec("currency_per_hour", 1.0, 100_000.0, 2000.0),
            "delivery_cost_hourly": ParamSpec("currency_per_hour", 0.0, 100_000.0, 800.0),
            "hours_per_month":      ParamSpec("count", 1.0, 400.0, 160.0),
            "utilisation":          ParamSpec("fraction", 0.01, 1.0, 0.6),
            "client_churn_monthly": ParamSpec("fraction", 0.0001, 0.99, 0.08),
            "cac":                  ParamSpec("currency", 0.0, 10_000_000.0, 20000.0),
            "fixed_monthly":        ParamSpec("currency", 0.0, 100_000_000.0, 100000.0),
        },
    ),
}
