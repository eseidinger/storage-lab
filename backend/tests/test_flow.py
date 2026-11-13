from collections.abc import Generator

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from storage_lab.api import app
from storage_lab.auth import Principal, current_principal
from storage_lab.db import Base, get_session
from storage_lab.models import AuditEvent, Operation
from storage_lab.settings import Settings
from storage_lab.worker import run_once


class FakeAdapter:
    def __init__(self):
        self.resources: set[str] = set()
        self.credentials: dict[str, str] = {}

    def provision(self, project_id: str):
        self.resources.add(project_id)
        return f"sl_{project_id}", {"host": "localhost"}

    def issue(self, project_id: str, username: str, secret: str, access: str = "runtime"):
        assert project_id in self.resources
        self.credentials[username] = secret

    def revoke(self, project_id: str, username: str):
        self.credentials.pop(username, None)

    def delete(self, project_id: str):
        self.resources.discard(project_id)


@pytest.fixture
def environment(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    active = {"principal": Principal("https://idp.example/realms/dev", "alice")}

    def session_override() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[current_principal] = lambda: active["principal"]
    adapter = FakeAdapter()
    monkeypatch.setattr("storage_lab.worker.adapter_for", lambda kind, settings: adapter)
    settings = Settings(credential_key=Fernet.generate_key().decode())
    monkeypatch.setattr("storage_lab.api.get_settings", lambda: settings)
    with TestClient(app) as client:
        yield client, factory, active, adapter, settings
    app.dependency_overrides.clear()
    engine.dispose()


def test_project_isolation_and_provisioning(environment):
    client, factory, active, adapter, settings = environment
    project = client.post("/projects", json={"name": "Alpha"}).json()
    project_id = project["id"]
    assert project["role"] == "admin"
    assert len(client.get("/projects").json()) == 1

    first = client.put(f"/projects/{project_id}/capabilities/postgresql").json()
    again = client.put(f"/projects/{project_id}/capabilities/postgresql").json()
    assert first["id"] == again["id"]
    assert run_once(factory, settings)
    assert client.get(f"/operations/{first['id']}").json()["state"] == "succeeded"
    assert client.get(f"/projects/{project_id}/capabilities/postgresql").json()["state"] == "ready"
    assert project_id in adapter.resources

    active["principal"] = Principal("https://idp.example/realms/dev", "bob")
    assert client.get(f"/projects/{project_id}").status_code == 404
    assert client.get(f"/operations/{first['id']}").status_code == 404
    assert client.put(f"/projects/{project_id}/capabilities/postgresql").status_code == 404
    assert client.get("/projects").json() == []


def test_credential_lifecycle_and_confirmed_deletion(environment):
    client, factory, active, adapter, settings = environment
    project_id = client.post("/projects", json={"name": "Alpha"}).json()["id"]
    client.put(f"/projects/{project_id}/capabilities/object-storage")
    assert run_once(factory, settings)

    issued = client.post(
        f"/projects/{project_id}/capabilities/object-storage/credentials",
        json={"label": "application"},
    ).json()
    secret = issued["secret"]
    username = issued["credential"]["username"]
    assert secret not in str(client.get(f"/operations/{issued['operation']['id']}").json())
    assert run_once(factory, settings)
    assert adapter.credentials[username] == secret
    with factory() as session:
        operation = session.get(Operation, issued["operation"]["id"])
        assert operation.payload is None
        assert secret not in str(session.scalars(select(AuditEvent)).all())

    credential_id = issued["credential"]["id"]
    client.delete(f"/projects/{project_id}/capabilities/object-storage/credentials/{credential_id}")
    assert run_once(factory, settings)
    assert username not in adapter.credentials

    url = f"/projects/{project_id}/capabilities/object-storage"
    assert client.request("DELETE", url, json={"confirm_name": "Wrong"}).status_code == 400
    deletion = client.request("DELETE", url, json={"confirm_name": "Alpha"}).json()
    assert run_once(factory, settings)
    assert client.get(f"/operations/{deletion['id']}").json()["state"] == "succeeded"
    assert client.get(url).status_code == 404
    assert project_id not in adapter.resources


def test_membership_roles(environment):
    client, factory, active, adapter, settings = environment
    project_id = client.post("/projects", json={"name": "Alpha"}).json()["id"]
    client.post(
        f"/projects/{project_id}/members",
        json={"issuer": active["principal"].issuer, "subject": "bob", "role": "viewer"},
    )
    active["principal"] = Principal("https://idp.example/realms/dev", "bob")
    assert client.get(f"/projects/{project_id}").status_code == 200
    assert client.put(f"/projects/{project_id}/capabilities/postgresql").status_code == 404


def test_only_admin_cannot_be_demoted_and_migration_access_is_postgresql_only(environment):
    client, factory, active, adapter, settings = environment
    project_id = client.post("/projects", json={"name": "Alpha"}).json()["id"]
    assert client.post(
        f"/projects/{project_id}/members",
        json={"issuer": active["principal"].issuer, "subject": active["principal"].subject, "role": "viewer"},
    ).status_code == 409
    operation = client.put(f"/projects/{project_id}/capabilities/object-storage").json()
    assert run_once(factory, settings)
    response = client.post(
        f"/projects/{project_id}/capabilities/object-storage/credentials",
        json={"label": "migration", "access": "migration"},
    )
    assert response.status_code == 422
    assert client.get(f"/operations/{operation['id']}").json()["state"] == "succeeded"


def test_failed_operation_can_be_retried_without_duplicate_resource(environment, monkeypatch):
    client, factory, active, adapter, settings = environment
    project_id = client.post("/projects", json={"name": "Retry"}).json()["id"]
    operation = client.put(f"/projects/{project_id}/capabilities/postgresql").json()
    original = adapter.provision

    def fail_once(project):
        monkeypatch.setattr(adapter, "provision", original)
        raise RuntimeError("temporary failure")

    monkeypatch.setattr(adapter, "provision", fail_once)
    assert run_once(factory, settings)
    failed = client.get(f"/operations/{operation['id']}").json()
    assert failed["state"] == "failed"
    assert "temporary failure" not in str(failed)
    assert client.post(f"/operations/{operation['id']}/retry").status_code == 202
    assert run_once(factory, settings)
    assert client.get(f"/operations/{operation['id']}").json()["state"] == "succeeded"
    assert adapter.resources == {project_id}
