import logging
import time
from datetime import timedelta

import httpx
import psycopg
from botocore.exceptions import ClientError
from cryptography.fernet import Fernet
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from .adapters import adapter_for
from .db import session_factory
from .models import Capability, Credential, Operation, now
from .settings import Settings, get_settings


log = logging.getLogger(__name__)


def public_error(exc: Exception) -> str:
    if isinstance(exc, ClientError):
        return f"S3 error: {exc.response.get('Error', {}).get('Code', 'unknown')}"
    if isinstance(exc, psycopg.Error):
        return f"PostgreSQL error: {exc.sqlstate or 'unknown'}"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Service HTTP error: {exc.response.status_code}"
    return f"Service error: {type(exc).__name__}"


def claim(factory: sessionmaker[Session]) -> str | None:
    with factory.begin() as session:
        operation = session.scalar(
            select(Operation)
            .where(
                or_(
                    Operation.state == "pending",
                    and_(Operation.state == "running", Operation.lease_until < now()),
                )
            )
            .order_by(Operation.created_at, Operation.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if operation is None:
            return None
        operation.state = "running"
        operation.attempts += 1
        operation.lease_until = now() + timedelta(minutes=5)
        return operation.id


def process(operation_id: str, factory: sessionmaker[Session], settings: Settings) -> None:
    with factory() as session:
        operation = session.get(Operation, operation_id)
        if operation is None:
            return
        kind = operation.capability_kind
        project_id = operation.project_id
        action = operation.action
        payload = operation.payload or {}

    try:
        adapter = adapter_for(kind, settings)
        result = None
        if action == "provision":
            result = adapter.provision(project_id)
            if kind in {"object-storage", "documents"}:
                if not settings.credential_key:
                    raise RuntimeError("Credential encryption is not configured")
                with factory() as session:
                    capability = session.scalar(
                        select(Capability).where(Capability.project_id == project_id, Capability.kind == kind)
                    )
                    sealed = capability.browser_credential if capability is not None else None
                if not sealed:
                    raise RuntimeError("Browser credential is missing")
                secret = Fernet(settings.credential_key).decrypt(sealed["encrypted_secret"].encode()).decode()
                adapter.issue(project_id, sealed["username"], secret)
        elif action == "delete":
            with factory() as session:
                credentials = session.scalars(
                    select(Credential).where(
                        Credential.project_id == project_id,
                        Credential.capability_kind == kind,
                    )
                ).all()
                usernames = [credential.username for credential in credentials]
                capability = session.scalar(
                    select(Capability).where(Capability.project_id == project_id, Capability.kind == kind)
                )
                if kind in {"object-storage", "documents"} and capability is not None and capability.browser_credential:
                    usernames.append(capability.browser_credential["username"])
            for username in usernames:
                adapter.revoke(project_id, username)
            adapter.delete(project_id)
        elif action == "issue_credential":
            if not settings.credential_key:
                raise RuntimeError("Credential encryption is not configured")
            with factory() as session:
                credential = session.get(Credential, payload["credential_id"])
                if credential is None:
                    raise RuntimeError("Credential record not found")
                username = credential.username
                access = credential.access
            secret = Fernet(settings.credential_key).decrypt(payload["encrypted_secret"].encode()).decode()
            issued_secret = adapter.issue(project_id, username, secret, access)
        elif action == "revoke_credential":
            with factory() as session:
                credential = session.get(Credential, payload["credential_id"])
                username = credential.username if credential is not None else None
            if username:
                adapter.revoke(project_id, username)
        else:
            raise RuntimeError(f"Unknown operation action: {action}")

        with factory.begin() as session:
            operation = session.get(Operation, operation_id)
            operation.state = "succeeded"
            operation.error = None
            operation.lease_until = None
            operation.payload = None
            capability = session.scalar(
                select(Capability).where(Capability.project_id == project_id, Capability.kind == kind)
            )
            if action == "provision" and capability is not None:
                capability.state = "ready"
                capability.resource_name, capability.endpoint = result
                capability.error = None
            elif action == "delete":
                for credential in session.scalars(
                    select(Credential).where(
                        Credential.project_id == project_id,
                        Credential.capability_kind == kind,
                    )
                ):
                    session.delete(credential)
                if capability is not None:
                    session.delete(capability)
            elif action == "issue_credential":
                credential = session.get(Credential, payload["credential_id"])
                if credential is not None:
                    credential.state = "ready"
                    if issued_secret is not None:
                        credential.deliverable_secret = Fernet(settings.credential_key).encrypt(issued_secret.encode()).decode()
            elif action == "revoke_credential":
                credential = session.get(Credential, payload["credential_id"])
                if credential is not None:
                    session.delete(credential)
    except Exception as exc:
        log.exception("Provisioning operation %s failed", operation_id)
        with factory.begin() as session:
            operation = session.get(Operation, operation_id)
            if operation is None:
                return
            operation.state = "failed"
            operation.error = public_error(exc)
            operation.lease_until = None
            capability = session.scalar(
                select(Capability).where(Capability.project_id == project_id, Capability.kind == kind)
            )
            if capability is not None and action in {"provision", "delete"}:
                capability.state = "failed"
                capability.error = operation.error
            if action == "issue_credential":
                credential = session.get(Credential, payload.get("credential_id"))
                if credential is not None:
                    credential.state = "failed"


def run_once(factory: sessionmaker[Session] | None = None, settings: Settings | None = None) -> bool:
    factory = factory or session_factory()
    settings = settings or get_settings()
    operation_id = claim(factory)
    if operation_id is None:
        return False
    process(operation_id, factory, settings)
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    factory = session_factory()
    while True:
        if not run_once(factory, settings):
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
