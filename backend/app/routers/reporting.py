from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from io import StringIO
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, ForeignKey, JSON, String, Uuid, select, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base, get_db
from app.routers.assessments import Assessment
from app.routers.auth import User, get_current_user, require_roles
from app.routers.configuration import EvaluationPeriod, KPI
from app.routers.organization import Department, Employee
from app.routers.recommendations import Recommendation
from app.services.audit import AuditEvent, record_audit

router = APIRouter(tags=["dashboard, reporting, audit, and evidence"])


class AssessmentEvidence(Base):
    __tablename__ = "assessment_evidence"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(String(2000))
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    added_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class EvidenceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    source_url: AnyHttpUrl | None = None


class EvidenceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    assessment_id: UUID
    title: str
    summary: str
    source_url: str | None
    added_by: UUID
    created_at: datetime


class DashboardSummary(BaseModel):
    period_id: UUID
    period_name: str
    active_employees: int
    departments: int
    self_assessments: int
    supervisor_assessments: int
    average_supervisor_score: Decimal | None
    recommendations_pending: int
    recommendations_approved: int
    recommendations_rejected: int


class AuditEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    actor_id: UUID | None
    action: str
    resource_type: str
    resource_id: str
    details: dict
    created_at: datetime


def _assessment_allowed(assessment: Assessment, user: User, db: Session) -> bool:
    if user.role in {"admin", "hr"}:
        return True
    if user.employee_id is None:
        return False
    if assessment.employee_id == user.employee_id:
        return True
    if user.role == "supervisor":
        employee = db.get(Employee, assessment.employee_id)
        return employee is not None and employee.supervisor_id == user.employee_id
    return False


@router.get("/dashboard/periods/{period_id}", response_model=DashboardSummary)
def dashboard(period_id: UUID, db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr"))) -> DashboardSummary:
    period = db.get(EvaluationPeriod, period_id)
    if period is None:
        raise HTTPException(status_code=404, detail="Evaluation period not found")
    assessments = list(db.scalars(select(Assessment).where(Assessment.period_id == period_id)))
    recommendations = list(db.scalars(select(Recommendation).where(Recommendation.period_id == period_id)))
    supervisor_scores: list[Decimal] = []
    for assessment in assessments:
        if assessment.assessment_type != "supervisor":
            continue
        score_by_kpi = {item.kpi_id: item.score for item in assessment.scores}
        kpis = list(db.scalars(select(KPI).where(KPI.id.in_(score_by_kpi))))
        weighted = [(score_by_kpi[kpi.id], Decimal(str(kpi.default_weight))) for kpi in kpis]
        weight_total = sum((weight for _, weight in weighted), Decimal("0"))
        if weight_total > 0:
            supervisor_scores.append(sum((score * weight for score, weight in weighted), Decimal("0")) / weight_total)
    average_score = None
    if supervisor_scores:
        average_score = (sum(supervisor_scores, Decimal("0")) / len(supervisor_scores)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return DashboardSummary(
        period_id=period.id, period_name=period.name,
        active_employees=db.scalar(select(func.count(Employee.id)).where(Employee.is_active.is_(True))) or 0,
        departments=db.scalar(select(func.count(Department.id))) or 0,
        self_assessments=sum(item.assessment_type == "self" for item in assessments),
        supervisor_assessments=sum(item.assessment_type == "supervisor" for item in assessments),
        average_supervisor_score=average_score,
        recommendations_pending=sum(item.review_status == "pending" for item in recommendations),
        recommendations_approved=sum(item.review_status == "approved" for item in recommendations),
        recommendations_rejected=sum(item.review_status == "rejected" for item in recommendations),
    )


@router.get("/reports/periods/{period_id}.csv")
def period_report(period_id: UUID, db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr"))) -> StreamingResponse:
    period = db.get(EvaluationPeriod, period_id)
    if period is None:
        raise HTTPException(status_code=404, detail="Evaluation period not found")
    output = StringIO()
    output.write("employee_number,employee_name,department,period,supervisor_score,classification,kpi_gaps,recommendations,pending_reviews\n")
    employees = list(db.scalars(select(Employee).order_by(Employee.employee_number)))
    for employee in employees:
        assessment = db.scalar(select(Assessment).where(
            Assessment.employee_id == employee.id, Assessment.period_id == period.id,
            Assessment.assessment_type == "supervisor",
        ))
        if assessment is None:
            continue
        score_by_kpi = {item.kpi_id: item.score for item in assessment.scores}
        kpis = list(db.scalars(select(KPI).where(KPI.id.in_(score_by_kpi))))
        kpi_by_id = {item.id: item for item in kpis}
        weighted = [(score_by_kpi[kpi.id], Decimal(str(kpi.default_weight))) for kpi in kpis]
        weight_total = sum((weight for _, weight in weighted), Decimal("0"))
        if weight_total <= 0:
            continue
        score = (sum((value * weight for value, weight in weighted), Decimal("0")) / weight_total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        classification = "excellent" if score >= 80 else "satisfactory" if score >= 60 else "needs_improvement"
        gaps = ";".join(kpi_by_id[kpi_id].code for kpi_id, value in score_by_kpi.items() if value < 50 and kpi_id in kpi_by_id)
        recommendations = list(db.scalars(select(Recommendation).where(Recommendation.employee_id == employee.id, Recommendation.period_id == period.id)))
        pending = sum(item.review_status == "pending" for item in recommendations)
        department = db.get(Department, employee.department_id)
        cells = [employee.employee_number, employee.full_name, department.name if department else "", period.name,
                 f"{score:.2f}", classification, gaps, str(len(recommendations)), str(pending)]
        safe_cells = ["'" + cell if cell[:1] in {"=", "+", "-", "@"} else cell for cell in cells]
        escaped = ['"' + cell.replace('"', '""') + '"' for cell in safe_cells]
        output.write(",".join(escaped) + "\n")
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="performance-{period.name}.csv"'})


@router.post("/assessments/{assessment_id}/evidence", response_model=EvidenceView, status_code=201)
def add_evidence(assessment_id: UUID, request: EvidenceCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> AssessmentEvidence:
    assessment = db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if not _assessment_allowed(assessment, user, db):
        raise HTTPException(status_code=403, detail="You cannot access this assessment")
    evidence = AssessmentEvidence(assessment_id=assessment.id, title=request.title.strip(), summary=request.summary.strip(),
                                 source_url=str(request.source_url) if request.source_url else None, added_by=user.id)
    db.add(evidence)
    db.flush()
    record_audit(db, user.id, "evidence.added", "assessment_evidence", str(evidence.id), {"assessment_id": str(assessment.id)})
    db.commit()
    db.refresh(evidence)
    return evidence


@router.get("/assessments/{assessment_id}/evidence", response_model=list[EvidenceView])
def list_evidence(assessment_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[AssessmentEvidence]:
    assessment = db.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if not _assessment_allowed(assessment, user, db):
        raise HTTPException(status_code=403, detail="You cannot access this assessment")
    return list(db.scalars(select(AssessmentEvidence).where(AssessmentEvidence.assessment_id == assessment_id).order_by(AssessmentEvidence.created_at)))


@router.get("/audit-events", response_model=list[AuditEventView])
def audit_history(
    resource_type: str | None = None, resource_id: str | None = None, limit: int = 100,
    db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr")),
) -> list[AuditEvent]:
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    query = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    if resource_type:
        query = query.where(AuditEvent.resource_type == resource_type)
    if resource_id:
        query = query.where(AuditEvent.resource_id == resource_id)
    return list(db.scalars(query))
