from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import json
import secrets
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.config import settings
from app.database import Base, get_db

router = APIRouter(prefix="/auth", tags=["authentication"])
bearer = HTTPBearer(auto_error=False)
ROLES = {"admin", "hr", "supervisor", "employee"}


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(30))
    employee_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("employees.id"), unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=256)
    role: str
    employee_id: UUID | None = None


class UserView(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str
    role: str
    employee_id: UUID | None
    is_active: bool


def _password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"{salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        salt_hex, expected = encoded.split("$", 1)
        actual = _password_hash(password, bytes.fromhex(salt_hex)).split("$", 1)[1]
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _create_token(user: User) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = datetime.now(UTC)
    payload = {"sub": str(user.id), "role": user.role, "iat": int(now.timestamp()),
               "exp": int((now + timedelta(minutes=settings.access_token_minutes)).timestamp())}
    encode = lambda data: base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode().rstrip("=")
    body = f"{encode(header)}.{encode(payload)}"
    signature = hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None:
        raise unauthorized
    try:
        header, payload, signature = credentials.credentials.split(".")
        body = f"{header}.{payload}"
        expected = hmac.new(settings.jwt_secret.encode(), body.encode(), hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        if not hmac.compare_digest(expected, supplied):
            raise unauthorized
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if claims["exp"] <= datetime.now(UTC).timestamp():
            raise unauthorized
        user_id = UUID(claims["sub"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise unauthorized
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


def require_roles(*roles: str):
    def check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user
    return check


@router.post("/login")
def login(request: LoginRequest, db: Session = Depends(get_db)) -> dict[str, str | int]:
    user = db.scalar(select(User).where(User.email == request.email.lower()))
    if user is None or not user.is_active or not _verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password", headers={"WWW-Authenticate": "Bearer"})
    return {"access_token": _create_token(user), "token_type": "bearer", "expires_in": settings.access_token_minutes * 60}


@router.get("/me", response_model=UserView)
def read_me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/users", response_model=UserView, status_code=201)
def create_user(request: UserCreate, db: Session = Depends(require_roles("admin"))) -> User:
    if request.role not in ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of: {', '.join(sorted(ROLES))}")
    email = str(request.email).lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="Email is already registered")
    if request.role in {"employee", "supervisor"} and request.employee_id is None:
        raise HTTPException(status_code=422, detail="employee_id is required for employee and supervisor accounts")
    if request.employee_id is not None:
        from app.routers.organization import Employee
        employee = db.get(Employee, request.employee_id)
        if employee is None or not employee.is_active:
            raise HTTPException(status_code=404, detail="Active employee record not found")
    user = User(email=email, full_name=request.full_name.strip(), password_hash=_password_hash(request.password), role=request.role, employee_id=request.employee_id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user







