from pydantic import BaseModel, ConfigDict, Field

from jury.schemas.enums import Provenance


class Parameter(BaseModel):
    """PRD §16.5: every parameter carries provenance, which is what lets
    sensitivity mechanically nominate the next experiment (PRD §16.6)."""
    model_config = ConfigDict(extra="forbid")
    value: float
    unit: str
    provenance: Provenance
    source_id: str | None = None
    assumption_id: str | None = None


class Breakpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variable: str
    threshold: float
    direction: str = Field(pattern="^(above|below)$")
    unit: str
    output: str
    sentence: str


class SensitivityEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variable: str
    elasticity: float
    provenance: Provenance


class ModelOutputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contribution_margin: float
    ltv: float
    ltv_cac: float
    payback_months: float | None
    breakeven_volume_monthly: float | None
