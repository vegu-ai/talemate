from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from talemate.world_state.templates.decision_checks import DecisionCheckKind


class DecisionFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    passage_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    kind: DecisionCheckKind
    instructions: str = Field(min_length=1)
    p_true: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)


decision_findings_adapter = TypeAdapter(list[DecisionFinding])
