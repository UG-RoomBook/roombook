from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AdminRequest(Base):
    __tablename__ = "admin_requests"
    __table_args__ = (CheckConstraint("jsonb_typeof(result) = 'object'", name="result_object"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("application_users.id"), primary_key=True)
    key: Mapped[UUID] = mapped_column(primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
