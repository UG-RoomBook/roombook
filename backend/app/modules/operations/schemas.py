from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["healthy"] = "healthy"


class ReadinessResponse(BaseModel):
    status: Literal["ready"] = "ready"


class RuntimeVersion(BaseModel):
    commit_sha: str
    environment: str
    version: str
