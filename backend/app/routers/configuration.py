from datetime import date, datetime, UTC
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Boolean, Date, DateTime, Numeric, String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base, get_db
from app.routers.auth import User, require_roles

router = APIRouter(tags=["performance configuration"])


class KPI(Base):
    __tablename__ = "kpis"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(String)
    default_weight: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class EvaluationPeriod(Base):
    __tablename__ = "evaluation_periods"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class KPICreate(BaseModel):
    code: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=150)
    description: str = Field(min_length=1, max_length=4000)
    default_weight: float = Field(default=0, ge=0, le=100)


class KPIView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
    description: str
    default_weight: float
    is_active: bool
    created_at: datetime


class EvaluationPeriodCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class EvaluationPeriodView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    start_date: date
    end_date: date
    is_active: bool
    created_at: datetime


def _conflict(db: Session, message: str, operation) -> None:
    try:
        operation()
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=message) from error


@router.post("/kpis", response_model=KPIView, status_code=201)
def create_kpi(request: KPICreate, db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr"))) -> KPI:
    kpi = KPI(code=request.code.upper(), name=request.name.strip(), description=request.description.strip(), default_weight=request.default_weight)
    db.add(kpi)
    _conflict(db, "KPI code already exists", db.flush)
    db.refresh(kpi)
    return kpi


@router.get("/kpis", response_model=list[KPIView])
def list_kpis(include_inactive: bool = False, db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr", "supervisor", "employee"))) -> list[KPI]:
    query = select(KPI).order_by(KPI.code)
    if not include_inactive:
        query = query.where(KPI.is_active.is_(True))
    return list(db.scalars(query))


@router.patch("/kpis/{kpi_id}/deactivate", response_model=KPIView)
def deactivate_kpi(kpi_id: UUID, db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr"))) -> KPI:
    kpi = db.get(KPI, kpi_id)
    if kpi is None:
        raise HTTPException(status_code=404, detail="KPI not found")
    kpi.is_active = False
    db.commit()
    db.refresh(kpi)
    return kpi


@router.post("/evaluation-periods", response_model=EvaluationPeriodView, status_code=201)
def create_evaluation_period(request: EvaluationPeriodCreate, db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr"))) -> EvaluationPeriod:
    period = EvaluationPeriod(name=request.name.strip(), start_date=request.start_date, end_date=request.end_date)
    db.add(period)
    _conflict(db, "Evaluation period name already exists", db.flush)
    db.refresh(period)
    return period


@router.get("/evaluation-periods", response_model=list[EvaluationPeriodView])
def list_evaluation_periods(include_inactive: bool = False, db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr", "supervisor", "employee"))) -> list[EvaluationPeriod]:
    query = select(EvaluationPeriod).order_by(EvaluationPeriod.start_date.desc())
    if not include_inactive:
        query = query.where(EvaluationPeriod.is_active.is_(True))
    return list(db.scalars(query))


@router.patch("/evaluation-periods/{period_id}/deactivate", response_model=EvaluationPeriodView)
def deactivate_evaluation_period(period_id: UUID, db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr"))) -> EvaluationPeriod:
    period = db.get(EvaluationPeriod, period_id)
    if period is None:
        raise HTTPException(status_code=404, detail="Evaluation period not found")
    period.is_active = False
    db.commit()
    db.refresh(period)
    return period
