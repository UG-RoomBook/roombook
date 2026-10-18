from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SessionUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    role: Literal["Member", "Admin"]


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: SessionUser
    aal: Literal["aal1", "aal2"]
    purpose: Literal["standard"] = "standard"
    expires_at: datetime
    csrf_token: str
