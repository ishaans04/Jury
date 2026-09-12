import re

from pydantic import BaseModel, ConfigDict, field_validator

from jury.schemas.enums import Geo, Segment, Tier

_PERIOD = re.compile(r"^\d{4}(-Q[1-4])?$")


class Scope(BaseModel):
    """Typed applicability of a claim (PRD §12.2). Enumerated so overlap is computable."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    geo: Geo
    segment: Segment
    tier: Tier | None = None
    period: str | None = None

    @field_validator("period")
    @classmethod
    def _period_shape(cls, v: str | None) -> str | None:
        if v is not None and not _PERIOD.match(v):
            raise ValueError("period must be YYYY or YYYY-Qn")
        return v
