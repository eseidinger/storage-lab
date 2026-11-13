from uuid import uuid4
from secrets import token_urlsafe

import boto3
from botocore.config import Config
from fastapi import File, UploadFile
from fastapi.responses import StreamingResponse

from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, current_principal
from .db import get_session
from .models import AuditEvent, Capability, Credential, Membership, Operation, Project
from .schemas import (
    CapabilityView,
    CredentialCreate,
    CredentialView,
    DeleteConfirmation,
    IssuedCredential,
    MemberCreate,
    MemberView,
    OperationView,
    ProjectCreate,
    ProjectView,
)
from .settings import get_settings


app = FastAPI(title="Storage Lab API", version="0.1.0")
SUPPORTED_CAPABILITIES = {"postgresql", "object-storage"}


def membership(session: Session, project_id: str, principal: Principal, admin: bool = False) -> Membership:
    member = session.scalar(
        select(Membership).where(
            Membership.project_id == project_id,
            Membership.identity == principal.identity,
        )
    )
    if member is None or (admin and member.role != "admin"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return member


def project_view(project: Project, member: Membership) -> ProjectView:
    return ProjectView(id=project.id, name=project.name, role=member.role, created_at=project.created_at)


def operation_view(operation: Operation) -> OperationView:
    return OperationView.model_validate(operation, from_attributes=True)


def capability_view(capability: Capability) -> CapabilityView:
    return CapabilityView.model_validate(capability, from_attributes=True)


def credential_view(credential: Credential) -> CredentialView:
    return CredentialView.model_validate(credential, from_attributes=True)


def latest_operation(session: Session, project_id: str, kind: str, action: str) -> Operation | None:
    return session.scalar(
        select(Operation)
        .where(
            Operation.project_id == project_id,
            Operation.capability_kind == kind,
            Operation.action == action,
        )
        .order_by(Operation.created_at.desc(), Operation.id.desc())
        .limit(1)
    )


def add_audit(session: Session, project_id: str, actor: str, action: str, resource: str) -> None:
    session.add(AuditEvent(project_id=project_id, actor=actor, action=action, resource=resource))


def ensure_kind(kind: str) -> None:
    if kind not in SUPPORTED_CAPABILITIES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Capability is not implemented")


def browser_client(session: Session, project_id: str, principal: Principal):
    membership(session, project_id, principal)
    capability = session.scalar(
        select(Capability).where(
            Capability.project_id == project_id,
            Capability.kind == "object-storage",
        )
    )
    if capability is None or capability.state != "ready" or not capability.browser_credential:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Object storage is not ready")
    settings = get_settings()
    sealed = capability.browser_credential
    secret = Fernet(settings.credential_key).decrypt(sealed["encrypted_secret"].encode()).decode()
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=sealed["username"],
        aws_secret_access_key=secret,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    return client, capability.resource_name


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/projects", response_model=ProjectView, status_code=201)
def create_project(
    body: ProjectCreate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> ProjectView:
    project = Project(id=uuid4().hex, name=body.name.strip(), created_by=principal.identity)
    if not project.name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Project name is required")
    member = Membership(project_id=project.id, identity=principal.identity, role="admin")
    session.add(project)
    session.flush()
    session.add(member)
    add_audit(session, project.id, principal.identity, "project.create", project.id)
    session.commit()
    return project_view(project, member)


@app.get("/projects", response_model=list[ProjectView])
def list_projects(
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[ProjectView]:
    rows = session.execute(
        select(Project, Membership)
        .join(Membership, Membership.project_id == Project.id)
        .where(Membership.identity == principal.identity)
        .order_by(Project.created_at.desc())
    )
    return [project_view(project, member) for project, member in rows]


@app.get("/projects/{project_id}", response_model=ProjectView)
def get_project(
    project_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> ProjectView:
    member = membership(session, project_id, principal)
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project_view(project, member)


@app.get("/projects/{project_id}/members", response_model=list[MemberView])
def list_members(
    project_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[MemberView]:
    membership(session, project_id, principal)
    members = session.scalars(select(Membership).where(Membership.project_id == project_id)).all()
    result = []
    for member in members:
        issuer, subject = member.identity.split("::", 1)
        result.append(MemberView(issuer=issuer, subject=subject, role=member.role))
    return result


@app.post("/projects/{project_id}/members", response_model=MemberView)
def add_member(
    project_id: str,
    body: MemberCreate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> MemberView:
    membership(session, project_id, principal, admin=True)
    session.scalar(select(Project).where(Project.id == project_id).with_for_update())
    identity = f"{body.issuer}::{body.subject}"
    member = session.scalar(
        select(Membership).where(Membership.project_id == project_id, Membership.identity == identity)
    )
    if member is None:
        member = Membership(project_id=project_id, identity=identity, role=body.role)
        session.add(member)
    else:
        if member.role == "admin" and body.role != "admin":
            administrators = session.scalars(
                select(Membership).where(Membership.project_id == project_id, Membership.role == "admin")
            ).all()
            if len(administrators) <= 1:
                raise HTTPException(status.HTTP_409_CONFLICT, "A project must have an administrator")
        member.role = body.role
    add_audit(session, project_id, principal.identity, "member.upsert", identity)
    session.commit()
    return MemberView(issuer=body.issuer, subject=body.subject, role=member.role)


@app.get("/projects/{project_id}/capabilities", response_model=list[CapabilityView])
def list_capabilities(
    project_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[CapabilityView]:
    membership(session, project_id, principal)
    capabilities = session.scalars(select(Capability).where(Capability.project_id == project_id)).all()
    return [capability_view(item) for item in capabilities]


@app.get("/projects/{project_id}/capabilities/{kind}", response_model=CapabilityView)
def get_capability(
    project_id: str,
    kind: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> CapabilityView:
    membership(session, project_id, principal)
    capability = session.scalar(
        select(Capability).where(Capability.project_id == project_id, Capability.kind == kind)
    )
    if capability is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Capability not found")
    return capability_view(capability)


@app.put("/projects/{project_id}/capabilities/{kind}", response_model=OperationView, status_code=202)
def enable_capability(
    project_id: str,
    kind: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> OperationView:
    ensure_kind(kind)
    membership(session, project_id, principal, admin=True)
    session.scalar(select(Project).where(Project.id == project_id).with_for_update())
    capability = session.scalar(
        select(Capability)
        .where(Capability.project_id == project_id, Capability.kind == kind)
        .with_for_update()
    )
    if capability is not None and capability.state == "deleting":
        raise HTTPException(status.HTTP_409_CONFLICT, "Deletion is in progress")
    if capability is not None and capability.state in {"pending", "ready"}:
        previous = latest_operation(session, project_id, kind, "provision")
        if previous is not None:
            return operation_view(previous)
    if capability is None:
        capability = Capability(project_id=project_id, kind=kind, state="pending")
        session.add(capability)
    else:
        capability.state = "pending"
        capability.error = None
    if kind == "object-storage" and not capability.browser_credential:
        if not get_settings().credential_key:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Credential encryption is not configured")
        secret = token_urlsafe(36)
        capability.browser_credential = {
            "username": f"sl_browser_{project_id[:20]}",
            "encrypted_secret": Fernet(get_settings().credential_key).encrypt(secret.encode()).decode(),
        }
    operation = Operation(id=uuid4().hex, project_id=project_id, capability_kind=kind, action="provision")
    session.add(operation)
    add_audit(session, project_id, principal.identity, "capability.enable", kind)
    session.commit()
    return operation_view(operation)


@app.get("/projects/{project_id}/objects")
def list_objects(
    project_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[dict]:
    client, bucket = browser_client(session, project_id, principal)
    objects = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        objects.extend({"key": item["Key"], "size": item["Size"]} for item in page.get("Contents", []))
    return objects


@app.post("/projects/{project_id}/objects", status_code=201)
def upload_object(
    project_id: str,
    file: UploadFile = File(...),
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> dict:
    membership(session, project_id, principal, admin=True)
    client, bucket = browser_client(session, project_id, principal)
    key = file.filename or ""
    if not key or len(key) > 512:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid object name")
    client.upload_fileobj(file.file, bucket, key)
    return {"key": key}


@app.get("/projects/{project_id}/objects/download")
def download_object(
    project_id: str,
    key: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
):
    client, bucket = browser_client(session, project_id, principal)
    obj = client.get_object(Bucket=bucket, Key=key)
    filename = key.split("/")[-1].replace('"', '')
    return StreamingResponse(
        obj["Body"].iter_chunks(chunk_size=65536),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.delete("/projects/{project_id}/objects")
def delete_object(
    project_id: str,
    key: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> dict:
    membership(session, project_id, principal, admin=True)
    client, bucket = browser_client(session, project_id, principal)
    client.delete_object(Bucket=bucket, Key=key)
    return {"deleted": key}


@app.delete("/projects/{project_id}/capabilities/{kind}", response_model=OperationView, status_code=202)
def delete_capability(
    project_id: str,
    kind: str,
    body: DeleteConfirmation,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> OperationView:
    membership(session, project_id, principal, admin=True)
    project = session.get(Project, project_id)
    if project is None or body.confirm_name != project.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Confirm the exact project name")
    capability = session.scalar(
        select(Capability)
        .where(Capability.project_id == project_id, Capability.kind == kind)
        .with_for_update()
    )
    if capability is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Capability not found")
    if capability.state == "deleting":
        previous = latest_operation(session, project_id, kind, "delete")
        if previous is not None:
            return operation_view(previous)
    if capability.state == "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Provisioning is in progress")
    capability.state = "deleting"
    operation = Operation(id=uuid4().hex, project_id=project_id, capability_kind=kind, action="delete")
    session.add(operation)
    add_audit(session, project_id, principal.identity, "capability.delete", kind)
    session.commit()
    return operation_view(operation)


@app.get("/operations/{operation_id}", response_model=OperationView)
def get_operation(
    operation_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> OperationView:
    operation = session.get(Operation, operation_id)
    if operation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Operation not found")
    membership(session, operation.project_id, principal)
    return operation_view(operation)


@app.post("/operations/{operation_id}/retry", response_model=OperationView, status_code=202)
def retry_operation(
    operation_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> OperationView:
    operation = session.get(Operation, operation_id, with_for_update=True)
    if operation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Operation not found")
    membership(session, operation.project_id, principal, admin=True)
    if operation.state != "failed" or operation.attempts >= 5:
        raise HTTPException(status.HTTP_409_CONFLICT, "Operation cannot be retried")
    operation.state = "pending"
    operation.error = None
    capability = session.scalar(
        select(Capability).where(
            Capability.project_id == operation.project_id,
            Capability.kind == operation.capability_kind,
        )
    )
    if capability is not None and operation.action in {"provision", "delete"}:
        capability.state = "deleting" if operation.action == "delete" else "pending"
        capability.error = None
    if operation.action == "issue_credential" and operation.payload:
        credential = session.get(Credential, operation.payload["credential_id"])
        if credential is not None:
            credential.state = "pending"
    add_audit(session, operation.project_id, principal.identity, "operation.retry", operation.id)
    session.commit()
    return operation_view(operation)


@app.get("/projects/{project_id}/capabilities/{kind}/credentials", response_model=list[CredentialView])
def list_credentials(
    project_id: str,
    kind: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> list[CredentialView]:
    membership(session, project_id, principal, admin=True)
    credentials = session.scalars(
        select(Credential).where(Credential.project_id == project_id, Credential.capability_kind == kind)
    ).all()
    return [credential_view(item) for item in credentials]


@app.post("/projects/{project_id}/capabilities/{kind}/credentials", response_model=IssuedCredential, status_code=202)
def issue_credential(
    project_id: str,
    kind: str,
    body: CredentialCreate,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> IssuedCredential:
    ensure_kind(kind)
    membership(session, project_id, principal, admin=True)
    capability = session.scalar(
        select(Capability).where(Capability.project_id == project_id, Capability.kind == kind)
    )
    if capability is None or capability.state != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "Capability is not ready")
    if kind != "postgresql" and body.access != "runtime":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Migration access applies only to PostgreSQL")
    if not get_settings().credential_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Credential encryption is not configured")
    credential_id = uuid4().hex
    username = f"sl_{project_id[:10]}_{credential_id[:10]}"
    secret = token_urlsafe(36)
    encrypted = Fernet(get_settings().credential_key).encrypt(secret.encode()).decode()
    credential = Credential(
        id=credential_id,
        project_id=project_id,
        capability_kind=kind,
        label=body.label,
        access=body.access,
        username=username,
        state="pending",
    )
    operation = Operation(
        id=uuid4().hex,
        project_id=project_id,
        capability_kind=kind,
        action="issue_credential",
        payload={"credential_id": credential_id, "encrypted_secret": encrypted},
    )
    session.add_all([credential, operation])
    add_audit(session, project_id, principal.identity, "credential.issue", credential_id)
    session.commit()
    return IssuedCredential(credential=credential_view(credential), secret=secret, operation=operation_view(operation))


@app.delete("/projects/{project_id}/capabilities/{kind}/credentials/{credential_id}", response_model=OperationView, status_code=202)
def revoke_credential(
    project_id: str,
    kind: str,
    credential_id: str,
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_session),
) -> OperationView:
    membership(session, project_id, principal, admin=True)
    credential = session.get(Credential, credential_id, with_for_update=True)
    if credential is None or credential.project_id != project_id or credential.capability_kind != kind:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Credential not found")
    if credential.state == "revoking":
        previous = session.scalars(
            select(Operation)
            .where(Operation.action == "revoke_credential", Operation.project_id == project_id, Operation.capability_kind == kind)
            .order_by(Operation.created_at.desc(), Operation.id.desc())
        ).all()
        for previous in previous:
            if previous.payload and previous.payload.get("credential_id") == credential_id:
                return operation_view(previous)
    credential.state = "revoking"
    operation = Operation(
        id=uuid4().hex,
        project_id=project_id,
        capability_kind=kind,
        action="revoke_credential",
        payload={"credential_id": credential_id},
    )
    session.add(operation)
    add_audit(session, project_id, principal.identity, "credential.revoke", credential_id)
    session.commit()
    return operation_view(operation)
