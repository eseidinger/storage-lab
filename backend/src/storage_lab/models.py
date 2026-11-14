from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[str] = mapped_column(String(600), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("project_id", "identity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    identity: Mapped[str] = mapped_column(String(600), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)


class PlatformAdmin(Base):
    __tablename__ = "platform_admins"

    identity: Mapped[str] = mapped_column(String(600), primary_key=True)
    granted_by: Mapped[str] = mapped_column(String(600), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PlatformAdminEvent(Base):
    __tablename__ = "platform_admin_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(600), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    identity: Mapped[str] = mapped_column(String(600), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Capability(Base):
    __tablename__ = "capabilities"
    __table_args__ = (UniqueConstraint("project_id", "kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    resource_name: Mapped[str | None] = mapped_column(String(120))
    endpoint: Mapped[dict | None] = mapped_column(JSON)
    browser_credential: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)


class Operation(Base):
    __tablename__ = "operations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    capability_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Credential(Base):
    __tablename__ = "credentials"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    capability_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    access: Mapped[str] = mapped_column(String(20), nullable=False, default="runtime")
    username: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str] = mapped_column(String(600), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
