from pydantic import BaseModel, ConfigDict, Field, model_validator

from jury.schemas.enums import Chair, Direction
from jury.schemas.scope import Scope


class NewAssumption(BaseModel):
    """How a chair introduces an assumption the extractor missed (PRD §7.3)."""
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=10, max_length=300)
    class_key: str


class ClaimRecord(BaseModel):
    """The output contract for all five chairs. PRD §6.1, field-for-field.

    Every chair emits only typed claim records. No prose commentary is persisted
    or displayed except cross-examination transcripts.
    """
    model_config = ConfigDict(extra="forbid")

    assumption_id: str | None = None
    new_assumption: NewAssumption | None = None
    direction: Direction
    variable: str | None = None
    value_num: float | None = None
    value_min: float | None = None
    value_max: float | None = None
    unit: str | None = None
    scope: Scope
    confidence: float = Field(ge=0.0, le=1.0)
    source_url: str = Field(pattern=r"^https?://")
    source_tier: int = Field(ge=1, le=4)   # P1: tier 5 is not evidence
    excerpt: str = Field(min_length=1, max_length=240)
    chair: Chair

    @model_validator(mode="after")
    def _must_attach_to_an_assumption(self) -> "ClaimRecord":
        if self.assumption_id is None and self.new_assumption is None:
            raise ValueError("claim must reference assumption_id or supply new_assumption")
        return self

    @model_validator(mode="after")
    def _range_ordered(self) -> "ClaimRecord":
        if (self.value_min is not None and self.value_max is not None
                and self.value_min > self.value_max):
            raise ValueError("value_min must not exceed value_max")
        return self
