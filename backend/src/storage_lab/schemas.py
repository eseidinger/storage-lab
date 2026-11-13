from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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
    error: str | None


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
    created_at: datetime


class IssuedCredential(BaseModel):
    credential: CredentialView
    secret: str
    operation: OperationView


class DeleteConfirmation(BaseModel):
    confirm_name: str
