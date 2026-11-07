from decimal import Decimal

import pytest

from app.schemas.performance import KpiScore, PerformanceEvaluationRequest
from app.services.performance import calculate_evaluation


def test_calculates_weighted_score_and_identifies_gaps() -> None:
    request = PerformanceEvaluationRequest(
        employee_id="EMP-001",
        evaluation_period="2026-Q1",
        scores=[
            KpiScore(kpi_code="TASK_COMPLETION", score=80, weight=60),
            KpiScore(kpi_code="QUALITY", score=40, weight=40),
        ],
    )

    result = calculate_evaluation(request)

    assert result.overall_score == Decimal("64.00")
    assert result.classification == "satisfactory"
    assert result.gaps == ["QUALITY"]


def test_rejects_invalid_weight_total() -> None:
    request = PerformanceEvaluationRequest(
        employee_id="EMP-001",
        evaluation_period="2026-Q1",
        scores=[KpiScore(kpi_code="QUALITY", score=80, weight=50)],
    )

    with pytest.raises(ValueError, match="must total 100"):
        calculate_evaluation(request)
