from fastapi import APIRouter, Depends, HTTPException

from app.routers.auth import User, require_roles
from app.schemas.performance import PerformanceEvaluationRequest, PerformanceEvaluationResult
from app.services.performance import calculate_evaluation

router = APIRouter(prefix="/performance", tags=["performance"])


@router.post("/evaluate", response_model=PerformanceEvaluationResult)
def evaluate_performance(
    request: PerformanceEvaluationRequest,
    _user: User = Depends(require_roles("admin", "hr", "supervisor")),
) -> PerformanceEvaluationResult:
    try:
        return calculate_evaluation(request)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
