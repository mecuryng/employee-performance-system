from datetime import UTC, datetime
from decimal import Decimal
from string import Formatter
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import DateTime, ForeignKey, JSON, Numeric, String, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base, get_db
from app.routers.assessments import Assessment, AssessmentScore
from app.routers.auth import User, require_roles
from app.routers.configuration import EvaluationPeriod, KPI
from app.routers.organization import Employee
from app.services.audit import record_audit

router = APIRouter(tags=["recommendations and HR review"])
VALID_CONDITIONS = {"overall_score_below", "overall_score_at_least", "gap_kpi_codes", "disagreement_at_least"}
VALID_REVIEW_STATUSES = {"approved", "rejected"}


class RecommendationRule(Base):
    __tablename__ = "recommendation_rules"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(150))
    category: Mapped[str] = mapped_column(String(100))
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    conditions: Mapped[dict] = mapped_column(JSON)
    action: Mapped[str] = mapped_column(String)
    explanation_template: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = (UniqueConstraint("employee_id", "period_id", "rule_id", name="uq_recommendation_employee_period_rule"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employees.id"))
    period_id: Mapped[UUID] = mapped_column(ForeignKey("evaluation_periods.id"))
    rule_id: Mapped[UUID] = mapped_column(ForeignKey("recommendation_rules.id"))
    category: Mapped[str] = mapped_column(String(100))
    priority: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String)
    explanation: Mapped[str] = mapped_column(String)
    context: Mapped[dict] = mapped_column(JSON)
    review_status: Mapped[str] = mapped_column(String(20), default="pending")
    reviewer_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_note: Mapped[str] = mapped_column(String(2000), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    category: str = Field(min_length=1, max_length=100)
    priority: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    conditions: dict
    action: str = Field(min_length=1, max_length=4000)
    explanation_template: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_conditions(self):
        if not self.conditions or set(self.conditions) - VALID_CONDITIONS:
            raise ValueError(f"conditions must use one or more of: {', '.join(sorted(VALID_CONDITIONS))}")
        if "overall_score_below" in self.conditions and not 0 <= self.conditions["overall_score_below"] <= 100:
            raise ValueError("overall_score_below must be between 0 and 100")
        if "overall_score_at_least" in self.conditions and not 0 <= self.conditions["overall_score_at_least"] <= 100:
            raise ValueError("overall_score_at_least must be between 0 and 100")
        if "disagreement_at_least" in self.conditions and not 0 <= self.conditions["disagreement_at_least"] <= 100:
            raise ValueError("disagreement_at_least must be between 0 and 100")
        if "gap_kpi_codes" in self.conditions and not isinstance(self.conditions["gap_kpi_codes"], list):
            raise ValueError("gap_kpi_codes must be a list")
        allowed_fields = {"employee_name", "period_name", "overall_score", "gap_kpis", "category"}
        fields = {field for _, field, _, _ in Formatter().parse(self.explanation_template) if field}
        if fields - allowed_fields:
            raise ValueError(f"unsupported explanation fields: {', '.join(sorted(fields - allowed_fields))}")
        return self


class RuleView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    category: str
    priority: str
    conditions: dict
    action: str
    explanation_template: str
    is_active: bool
    created_at: datetime


class RecommendationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    employee_id: UUID
    period_id: UUID
    rule_id: UUID
    category: str
    priority: str
    action: str
    explanation: str
    context: dict
    review_status: str
    reviewer_id: UUID | None
    review_note: str
    reviewed_at: datetime | None
    created_at: datetime


class RecommendationReview(BaseModel):
    status: str
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_status(self):
        if self.status not in VALID_REVIEW_STATUSES:
            raise ValueError("status must be approved or rejected")
        return self


def _matches(conditions: dict, score: Decimal, gaps: set[str], disagreement: Decimal | None) -> bool:
    if "overall_score_below" in conditions and score >= Decimal(str(conditions["overall_score_below"])):
        return False
    if "overall_score_at_least" in conditions and score < Decimal(str(conditions["overall_score_at_least"])):
        return False
    if "gap_kpi_codes" in conditions and not set(conditions["gap_kpi_codes"]).intersection(gaps):
        return False
    if "disagreement_at_least" in conditions:
        threshold = Decimal(str(conditions["disagreement_at_least"]))
        if disagreement is None or disagreement < threshold:
            return False
    return True


@router.post("/recommendation-rules", response_model=RuleView, status_code=201)
def create_rule(request: RuleCreate, db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr"))) -> RecommendationRule:
    rule = RecommendationRule(**request.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/recommendation-rules", response_model=list[RuleView])
def list_rules(include_inactive: bool = False, db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr"))) -> list[RecommendationRule]:
    query = select(RecommendationRule).order_by(RecommendationRule.name)
    if not include_inactive:
        query = query.where(RecommendationRule.is_active.is_(True))
    return list(db.scalars(query))


@router.patch("/recommendation-rules/{rule_id}/deactivate", response_model=RuleView)
def deactivate_rule(rule_id: UUID, db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr"))) -> RecommendationRule:
    rule = db.get(RecommendationRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Recommendation rule not found")
    rule.is_active = False
    db.commit()
    db.refresh(rule)
    return rule


@router.post("/employees/{employee_id}/periods/{period_id}/recommendations", response_model=list[RecommendationView])
def evaluate_recommendations(employee_id: UUID, period_id: UUID, db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr"))) -> list[Recommendation]:
    employee = db.get(Employee, employee_id)
    period = db.get(EvaluationPeriod, period_id)
    if employee is None or period is None:
        raise HTTPException(status_code=404, detail="Employee or evaluation period not found")
    assessments = list(db.scalars(select(Assessment).where(
        Assessment.employee_id == employee_id, Assessment.period_id == period_id,
        Assessment.assessment_type.in_(["self", "supervisor"]),
    )))
    supervisor_assessment = next((item for item in assessments if item.assessment_type == "supervisor"), None)
    if supervisor_assessment is None:
        raise HTTPException(status_code=409, detail="A supervisor assessment is required before recommendations can be generated")
    self_assessment = next((item for item in assessments if item.assessment_type == "self"), None)
    supervisor_scores = {item.kpi_id: item.score for item in supervisor_assessment.scores}
    self_scores = {item.kpi_id: item.score for item in self_assessment.scores} if self_assessment else {}
    kpis = {item.id: item for item in db.scalars(select(KPI).where(KPI.id.in_(supervisor_scores)))}
    total_weight = sum((Decimal(str(kpis[kpi_id].default_weight)) for kpi_id in supervisor_scores if kpi_id in kpis), Decimal("0"))
    if total_weight <= 0:
        raise HTTPException(status_code=422, detail="Set positive default weights for KPIs before generating recommendations")
    overall = sum((score * Decimal(str(kpis[kpi_id].default_weight)) for kpi_id, score in supervisor_scores.items() if kpi_id in kpis), Decimal("0")) / total_weight
    overall = overall.quantize(Decimal("0.01"))
    gaps = {kpis[kpi_id].code for kpi_id, score in supervisor_scores.items() if kpi_id in kpis and score < 50}
    common = set(supervisor_scores).intersection(self_scores)
    disagreement = None
    if common:
        disagreement = (sum((abs(supervisor_scores[key] - self_scores[key]) for key in common), Decimal("0")) / len(common)).quantize(Decimal("0.01"))
    context = {
        "overall_score": float(overall), "gap_kpis": sorted(gaps),
        "self_assessment_available": self_assessment is not None,
        "self_supervisor_disagreement": float(disagreement) if disagreement is not None else None,
        "source_assessment": "supervisor", "period_name": period.name,
    }
    rules = db.scalars(select(RecommendationRule).where(RecommendationRule.is_active.is_(True))).all()
    existing = {
        item.rule_id: item for item in db.scalars(select(Recommendation).where(
            Recommendation.employee_id == employee_id, Recommendation.period_id == period_id,
        ))
    }
    matches = []
    for rule in rules:
        if not _matches(rule.conditions, overall, gaps, disagreement):
            continue
        if rule.id in existing:
            matches.append(existing[rule.id])
            continue
        explanation = rule.explanation_template.format(
            employee_name=employee.full_name, period_name=period.name,
            overall_score=f"{overall:.2f}", gap_kpis=", ".join(sorted(gaps)) or "none",
            category=rule.category,
        )
        recommendation = Recommendation(
            employee_id=employee_id, period_id=period_id, rule_id=rule.id,
            category=rule.category, priority=rule.priority, action=rule.action,
            explanation=explanation, context=context,
        )
        db.add(recommendation)
        db.flush()
        record_audit(db, _actor.id, "recommendation.generated", "recommendation", str(recommendation.id), {"employee_id": str(employee_id), "period_id": str(period_id), "rule_id": str(rule.id)})
        matches.append(recommendation)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Recommendations were generated concurrently; retry the request") from error
    return matches


@router.get("/recommendations", response_model=list[RecommendationView])
def list_recommendations(
    employee_id: UUID | None = None, period_id: UUID | None = None,
    db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr")),
) -> list[Recommendation]:
    query = select(Recommendation).order_by(Recommendation.created_at.desc())
    if employee_id is not None:
        query = query.where(Recommendation.employee_id == employee_id)
    if period_id is not None:
        query = query.where(Recommendation.period_id == period_id)
    return list(db.scalars(query))


@router.patch("/recommendations/{recommendation_id}/review", response_model=RecommendationView)
def review_recommendation(
    recommendation_id: UUID, request: RecommendationReview,
    db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "hr")),
) -> Recommendation:
    recommendation = db.get(Recommendation, recommendation_id)
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    if recommendation.review_status != "pending":
        raise HTTPException(status_code=409, detail="Recommendation has already been reviewed")
    recommendation.review_status = request.status
    recommendation.review_note = request.note.strip()
    recommendation.reviewer_id = user.id
    recommendation.reviewed_at = datetime.now(UTC)
    record_audit(db, user.id, "recommendation.reviewed", "recommendation", str(recommendation.id), {"status": request.status})
    db.commit()
    db.refresh(recommendation)
    return recommendation

