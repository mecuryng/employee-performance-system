from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, ForeignKey, String, Uuid, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base, get_db
from app.routers.auth import User, require_roles

router = APIRouter(tags=["organization"])


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    employee_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    designation: Mapped[str] = mapped_column(String(150))
    department_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("departments.id"))
    supervisor_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("employees.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)


class DepartmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    created_at: datetime


class EmployeeCreate(BaseModel):
    employee_number: str = Field(min_length=1, max_length=50)
    full_name: str = Field(min_length=1, max_length=200)
    designation: str = Field(min_length=1, max_length=150)
    department_id: UUID
    supervisor_id: UUID | None = None


class EmployeeView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    employee_number: str
    full_name: str
    designation: str
    department_id: UUID
    supervisor_id: UUID | None
    is_active: bool
    created_at: datetime


@router.post("/departments", response_model=DepartmentView, status_code=201)
def create_department(request: DepartmentCreate, db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr"))) -> Department:
    department = Department(name=request.name.strip())
    db.add(department)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Department name already exists") from error
    db.refresh(department)
    return department


@router.get("/departments", response_model=list[DepartmentView])
def list_departments(db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr", "supervisor"))) -> list[Department]:
    return list(db.scalars(select(Department).order_by(Department.name)))


@router.post("/employees", response_model=EmployeeView, status_code=201)
def create_employee(request: EmployeeCreate, db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr"))) -> Employee:
    if db.get(Department, request.department_id) is None:
        raise HTTPException(status_code=404, detail="Department not found")
    if request.supervisor_id is not None:
        supervisor = db.get(Employee, request.supervisor_id)
        if supervisor is None or not supervisor.is_active:
            raise HTTPException(status_code=404, detail="Active supervisor not found")
    employee = Employee(
        employee_number=request.employee_number.strip(), full_name=request.full_name.strip(),
        designation=request.designation.strip(), department_id=request.department_id,
        supervisor_id=request.supervisor_id,
    )
    db.add(employee)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Employee number already exists") from error
    db.refresh(employee)
    return employee


@router.get("/employees", response_model=list[EmployeeView])
def list_employees(department_id: UUID | None = None, db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr", "supervisor"))) -> list[Employee]:
    query = select(Employee).order_by(Employee.full_name)
    if department_id is not None:
        query = query.where(Employee.department_id == department_id)
    return list(db.scalars(query))


@router.patch("/employees/{employee_id}/deactivate", response_model=EmployeeView)
def deactivate_employee(employee_id: UUID, db: Session = Depends(get_db), _actor: User = Depends(require_roles("admin", "hr"))) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    employee.is_active = False
    db.commit()
    db.refresh(employee)
    return employee
