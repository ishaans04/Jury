from pydantic import BaseModel, ConfigDict, Field

from jury.schemas.enums import Decision


class ConfidenceComponents(BaseModel):
    """PRD §9.3: the UI always displays the four components alongside the total.
    A number with a visible decomposition is defensible; one without is not."""
    model_config = ConfigDict(extra="forbid")
    coverage: float = Field(ge=0.0, le=1.0)
    mean_strength: float = Field(ge=0.0, le=1.0)
    contradiction: float = Field(ge=0.0)
    open_critical: float = Field(ge=0.0, le=1.0)


class VerdictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Decision
    evidence_confidence: float = Field(ge=0.0, le=100.0)
    components: ConfidenceComponents
    gate_triggered: str | None
    friction: list[dict]
    rationale: str
