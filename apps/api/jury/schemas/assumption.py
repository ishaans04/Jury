from pydantic import BaseModel, ConfigDict, Field

from jury.schemas.enums import (
    AssumptionStatus, Chair, Criticality, Falsifiability, Origin, Uncertainty,
)


class AssumptionDraft(BaseModel):
    """Output of extraction, input to the hearing. Editable by the founder (F5)."""
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=10, max_length=300)
    class_key: str | None = None
    origin: Origin = Origin.FOUNDER
    discovered_by: Chair | None = None
    criticality: Criticality
    uncertainty: Uncertainty
    falsifiability: Falsifiability
    asserted_variable: str | None = None
    asserted_value: float | None = None
    asserted_unit: str | None = None


class AssumptionRecord(AssumptionDraft):
    id: str
    status: AssumptionStatus = AssumptionStatus.NO_EVIDENCE
    strength: float = Field(default=0.0, ge=0.0, le=1.0)
