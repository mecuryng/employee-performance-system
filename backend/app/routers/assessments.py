from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship, selectinload

from app.database import Base, get_db
from app.routers.auth import User, get_current_user, require_roles
from app.routers.configuration import EvaluationPeriod, KPI
from app.routers.organization import Employee
from app.services.audit import record_audit

router = APIRouter(prefix="/assessments", tags=["assessments"])


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (UniqueConstraint("employee_id", "period_id", "assessment_type", name="uq_assessment_employee_period_type"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employees.id"))
    period_id: Mapped[UUID] = mapped_column(ForeignKey("evaluation_periods.id"))
    assessment_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="submitted")
    comments: Mapped[str] = mapped_column(String(4000), default="")
    submitted_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    scores: Mapped[list["AssessmentScore"]] = relationship(back_populates="assessment", cascade="all, delete-orphan", lazy="selectin")


class AssessmentScore(Base):
    __tablename__ = "assessment_scores"
    __table_args__ = (UniqueConstraint("assessment_id", "kpi_id", name="uq_assessment_score_kpi"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    assessment_id: Mapped[UUID] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"))
    kpi_id: Mapped[UUID] = mapped_column(ForeignKey("kpis.id"))
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    comment: Mapped[str] = mapped_column(String(1000), default="")
    assessment: Mapped[Assessment] = relationship(back_populates="scores")


class AssessmentScoreInput(BaseModel):
    kpi_id: UUID
    score: Decimal = Field(ge=0, le=100)
    comment: str = Field(default="", max_length=1000)


class AssessmentCreate(BaseModel):
    period_id: UUID
    scores: list[AssessmentScoreInput] = Field(min_length=1)
    comments: str = Field(default="", max_length=4000)


class AssessmentScoreView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    kpi_id: UUID
    score: Decimal
    comment: str


class AssessmentView(BaseModel):
    id: UUID
    employee_id: UUID
    period_id: UUID
    assessment_type: str
    status: str
    comments: str
    submitted_by: UUID
    submitted_at: datetime
    scores: list[AssessmentScoreView]


def _submit(request: AssessmentCreate, assessment_type: str, employee_id: UUID, user: User, db: Session) -> Assessment:
    period = db.get(EvaluationPeriod, request.period_id)
    today = datetime.now(UTC).date()
    if period is None or not period.is_active or today < period.start_date or today > period.end_date:
        raise HTTPException(status_code=422, detail="Evaluation period is not currently open")
    kpi_ids = [item.kpi_id for item in request.scores]
    if len(kpi_ids) != len(set(kpi_ids)):
        raise HTTPException(status_code=422, detail="Each KPI can be scored only once")
    active_kpis = set(db.scalars(select(KPI.id).where(KPI.id.in_(kpi_ids), KPI.is_active.is_(True))))
    if active_kpis != set(kpi_ids):
        raise HTTPException(status_code=422, detail="Every score must reference an active KPI")
    assessment = Assessment(
        employee_id=employee_id, period_id=request.period_id, assessment_type=assessment_type,
        status="submitted", comments=request.comments.strip(), submitted_by=user.id,
        scores=[AssessmentScore(kpi_id=item.kpi_id, score=item.score, comment=item.comment.strip()) for item in request.scores],
    )
    db.add(assessment)
    try:
        db.flush()
        record_audit(db, user.id, "assessment.submitted", "assessment", str(assessment.id), {"type": assessment_type, "employee_id": str(employee_id), "period_id": str(request.period_id)})
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="This assessment has already been submitted for the period") from error
    db.refresh(assessment)
    return assessment


@router.post("/self", response_model=AssessmentView, status_code=201)
def submit_self_assessment(request: AssessmentCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("employee", "supervisor"))) -> Assessment:
    if user.employee_id is None:
        raise HTTPException(status_code=409, detail="Your account is not linked to an employee record")
    return _submit(request, "self", user.employee_id, user, db)


@router.post("/supervisor/{employee_id}", response_model=AssessmentView, status_code=201)
def submit_supervisor_assessment(employee_id: UUID, request: AssessmentCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("supervisor"))) -> Assessment:
    if user.employee_id is None:
        raise HTTPException(status_code=409, detail="Your account is not linked to a supervisor employee record")
    employee = db.get(Employee, employee_id)
    if employee is None or not employee.is_active:
        raise HTTPException(status_code=404, detail="Active employee not found")
    if employee.supervisor_id != user.employee_id:
        raise HTTPException(status_code=403, detail="You can assess only your direct reports")
    return _submit(request, "supervisor", employee_id, user, db)


@router.get("", response_model=list[AssessmentView])
def list_assessments(
    employee_id: UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Assessment]:
    query = select(Assessment).options(selectinload(Assessment.scores)).order_by(Assessment.submitted_at.desc())
    if user.role in {"admin", "hr"}:
        if employee_id is not None:
            query = query.where(Assessment.employee_id == employee_id)
    elif user.role == "supervisor":
        if user.employee_id is None:
            raise HTTPException(status_code=409, detail="Your account is not linked to a supervisor employee record")
        if employee_id is not None:
            employee = db.get(Employee, employee_id)
            if employee is None or employee.supervisor_id != user.employee_id:
                raise HTTPException(status_code=403, detail="You can view only your direct reports")
            query = query.where(Assessment.employee_id == employee_id)
        else:
            reports = select(Employee.id).where(Employee.supervisor_id == user.employee_id)
            query = query.where(Assessment.employee_id.in_(reports))
    elif user.role == "employee":
        if user.employee_id is None:
            raise HTTPException(status_code=409, detail="Your account is not linked to an employee record")
        if employee_id is not None and employee_id != user.employee_id:
            raise HTTPException(status_code=403, detail="You can view only your own assessments")
        query = query.where(Assessment.employee_id == user.employee_id)
    else:
        raise HTTPException(status_code=403, detail="Insufficient role")
    return list(db.scalars(query))

