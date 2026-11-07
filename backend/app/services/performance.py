from decimal import Decimal, ROUND_HALF_UP

from app.schemas.performance import PerformanceEvaluationRequest, PerformanceEvaluationResult


def calculate_evaluation(request: PerformanceEvaluationRequest) -> PerformanceEvaluationResult:
    total_weight = sum(item.weight for item in request.scores)
    if total_weight != Decimal("100"):
        raise ValueError("KPI weights must total 100")

    weighted_score = sum(item.score * item.weight / Decimal("100") for item in request.scores)
    overall_score = weighted_score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    gaps = [item.kpi_code for item in request.scores if item.score < Decimal("50")]

    if overall_score >= Decimal("80"):
        classification = "excellent"
    elif overall_score >= Decimal("60"):
        classification = "satisfactory"
    else:
        classification = "needs_improvement"

    return PerformanceEvaluationResult(
        employee_id=request.employee_id,
        evaluation_period=request.evaluation_period,
        overall_score=overall_score,
        classification=classification,
        gaps=gaps,
    )
