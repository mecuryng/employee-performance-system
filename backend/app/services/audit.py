from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, JSON, String, Uuid
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


def record_audit(db: Session, actor_id: UUID | None, action: str, resource_type: str, resource_id: str, details: dict | None = None) -> None:
    db.add(AuditEvent(actor_id=actor_id, action=action, resource_type=resource_type, resource_id=resource_id, details=details or {}))
