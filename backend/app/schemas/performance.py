from decimal import Decimal

from pydantic import BaseModel, Field


class KpiScore(BaseModel):
    kpi_code: str = Field(min_length=1, max_length=50)
    score: Decimal = Field(ge=0, le=100)
    weight: Decimal = Field(gt=0, le=100)


class PerformanceEvaluationRequest(BaseModel):
    employee_id: str = Field(min_length=1, max_length=50)
    evaluation_period: str = Field(min_length=1, max_length=50)
    scores: list[KpiScore] = Field(min_length=1)


class PerformanceEvaluationResult(BaseModel):
    employee_id: str
    evaluation_period: str
    overall_score: Decimal
    classification: str
    gaps: list[str]
