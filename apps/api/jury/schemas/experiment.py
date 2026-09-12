from pydantic import BaseModel, ConfigDict, Field

from jury.schemas.enums import Comparator, ExperimentMethod


class CriterionSpec(BaseModel):
    """P9: machine-evaluable kill criterion, pre-registered before the test runs.

    PRD §16.6: pre-registering the threshold is what stops the founder returning
    with an ambiguous result and rationalising it.
    """
    model_config = ConfigDict(extra="forbid")
    metric: str = Field(min_length=1)
    comparator: Comparator
    threshold: float
    n: int | None = Field(default=None, ge=1)


class ExperimentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assumption_id: str
    target_variable: str | None
    method: ExperimentMethod
    instructions: str = Field(min_length=20)
    kill_criterion: str = Field(min_length=10)   # P9, non-null
    criterion_spec: CriterionSpec
    est_cost: float | None = None
    est_days: int | None = None
    priority: int = Field(ge=1)
    limitation: str | None = None                # spec §26.6, retention proxy
