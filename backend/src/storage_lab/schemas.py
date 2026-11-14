from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class MemberCreate(BaseModel):
    issuer: str = Field(min_length=1, max_length=300)
    subject: str = Field(min_length=1, max_length=250)
    role: Literal["admin", "viewer"] = "viewer"


class MemberView(BaseModel):
    issuer: str
    subject: str
    role: str


class PlatformAdminCreate(BaseModel):
    issuer: str = Field(min_length=1, max_length=300)
    subject: str = Field(min_length=1, max_length=250)


class PlatformAdminView(PlatformAdminCreate):
    granted_by: str
    created_at: datetime


class ProjectView(BaseModel):
    id: str
    name: str
    role: str
    created_at: datetime


class CapabilityView(BaseModel):
    kind: str
    state: str
    resource_name: str | None
    endpoint: dict | None
    configuration: dict | None
    error: str | None


class CapabilityOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vector_size: int | None = Field(default=None, ge=1, le=65536)
    distance: Literal["Cosine", "Dot", "Euclid", "Manhattan"] | None = None
    stream_max_bytes: int | None = Field(default=None, ge=1048576, le=10737418240)


class OperationView(BaseModel):
    id: str
    project_id: str
    capability_kind: str
    action: str
    state: str
    attempts: int
    error: str | None
    created_at: datetime


class CredentialCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    access: Literal["runtime", "migration"] = "runtime"


class CredentialView(BaseModel):
    id: str
    label: str
    access: str
    username: str
    state: str
    delivery_pending: bool = False
    created_at: datetime


class IssuedCredential(BaseModel):
    credential: CredentialView
    secret: str | None
    operation: OperationView


class DeleteConfirmation(BaseModel):
    confirm_name: str
