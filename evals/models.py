from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import Place


class EvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvalExpectation(EvalModel):
    region_code: str = "SG"
    location_query_contains: list[str] = Field(default_factory=list)
    nearby_type_options: list[list[str]] = Field(default_factory=list)
    forbidden_types: list[str] = Field(default_factory=list)
    expected_recommendations: int = Field(default=0, ge=0)
    require_ranked_results: bool = False
    require_opening_hours: bool = False
    require_restaurant_details: bool = False
    location_not_found: bool = False


class EvalCase(EvalModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    description: str
    prompt: str
    text_results: list[Place]
    nearby_results: dict[str, list[Place]] = Field(default_factory=dict)
    expected: EvalExpectation

    @model_validator(mode="after")
    def validate_ground_truth(self) -> "EvalCase":
        available_types = set(self.nearby_results)
        for options in self.expected.nearby_type_options:
            if not available_types.intersection(options):
                raise ValueError(
                    "Every nearby type option must have matching fixture data"
                )
        if self.expected.location_not_found and self.text_results:
            raise ValueError("location_not_found cases cannot have text results")
        return self


class ToolCallRecord(EvalModel):
    tool: str
    parameters: dict[str, Any]


class EvalRun(EvalModel):
    case_id: str
    answer: str = ""
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    error: str | None = None


class GradeResult(EvalModel):
    name: str
    passed: bool
    score: float = Field(ge=0, le=1)
    detail: str


class JudgeResult(EvalModel):
    passed: bool
    score: float = Field(ge=0, le=1)
    rationale: str


class EvalCaseResult(EvalModel):
    case_id: str
    passed: bool
    deterministic_score: float = Field(ge=0, le=1)
    grades: list[GradeResult]
    run: EvalRun
    judge: JudgeResult | None = None


class EvalReport(EvalModel):
    model: str
    passed: bool
    pass_rate: float = Field(ge=0, le=1)
    cases: list[EvalCaseResult]
