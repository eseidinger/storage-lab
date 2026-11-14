"""Exercise API, worker, PostgreSQL, S3, and CouchDB in the development VM.

This script overrides only the external OIDC identity dependency because no
Developer Platform Keycloak configuration is shipped with the repository.
"""

import time
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from fastapi.testclient import TestClient

from storage_lab.api import app
from storage_lab.auth import Principal, current_principal
from storage_lab.settings import get_settings


def wait(client: TestClient, operation_id: str) -> None:
    for _ in range(60):
        operation = client.get(f"/operations/{operation_id}").json()
        if operation["state"] == "succeeded":
            return
        if operation["state"] == "failed":
            raise AssertionError(f"Operation failed: {operation['error']}")
        time.sleep(1)
    raise AssertionError("Operation did not finish within 60 seconds")


def main() -> None:
    settings = get_settings()
    alice = Principal("https://test.example/realms/dev", f"alice-{uuid4().hex}")
    bob = Principal("https://test.example/realms/dev", f"bob-{uuid4().hex}")
    active = {"principal": alice}
    app.dependency_overrides[current_principal] = lambda: active["principal"]
    projects: list[tuple[str, str, Principal]] = []
    with TestClient(app) as client:
        try:
            for owner, name in ((alice, "verify-a"), (bob, "verify-b")):
                active["principal"] = owner
                project = client.post("/projects", json={"name": name}).json()
                assert "id" in project, project
                projects.append((project["id"], name, owner))
                for kind in ("postgresql", "object-storage", "documents"):
                    operation = client.put(f"/projects/{project['id']}/capabilities/{kind}").json()
                    assert "id" in operation, operation
                    wait(client, operation["id"])

            first, second = projects[0][0], projects[1][0]
            active["principal"] = alice
            assert client.get(f"/projects/{second}").status_code == 404
            assert client.get(f"/projects/{second}/objects").status_code == 404
            upload = client.post(f"/projects/{first}/objects", files={"file": ("hello.txt", b"hello")})
            assert upload.status_code == 201, upload.text
            assert client.get(f"/projects/{first}/objects").json() == [{"key": "hello.txt", "size": 5}]
            download = client.get(f"/projects/{first}/objects/download", params={"key": "hello.txt"})
            assert download.content == b"hello"

            created_document = client.put(
                f"/projects/{first}/documents/verification", json={"value": "first"}
            )
            assert created_document.status_code == 200, created_document.text
            document = client.get(f"/projects/{first}/documents/verification")
            assert document.status_code == 200 and document.json()["value"] == "first", document.text
            assert client.get(f"/projects/{first}/documents").json()["items"][0]["id"] == "verification"
            revised = client.put(
                f"/projects/{first}/documents/verification",
                json={"_rev": document.json()["_rev"], "value": "updated"},
            )
            assert revised.status_code == 200, revised.text
            conflict = client.put(
                f"/projects/{first}/documents/verification",
                json={"_rev": document.json()["_rev"], "value": "stale"},
            )
            assert conflict.status_code == 409, conflict.text
            active["principal"] = bob
            assert client.get(f"/projects/{first}/documents").status_code == 404
            active["principal"] = alice
            added_viewer = client.post(
                f"/projects/{first}/members",
                json={"issuer": bob.issuer, "subject": bob.subject, "role": "viewer"},
            )
            assert added_viewer.status_code == 200, added_viewer.text
            active["principal"] = bob
            assert client.get(f"/projects/{first}/documents/verification").json()["value"] == "updated"
            assert client.put(
                f"/projects/{first}/documents/verification", json={"value": "forbidden"}
            ).status_code == 404
            active["principal"] = alice
            deleted_document = client.delete(
                f"/projects/{first}/documents/verification", params={"rev": revised.json()["rev"]}
            )
            assert deleted_document.status_code == 200, deleted_document.text
            assert client.get(f"/projects/{first}/documents/verification").status_code == 404

            issued_document = client.post(
                f"/projects/{first}/capabilities/documents/credentials",
                json={"label": "verification CouchDB"},
            ).json()
            assert "secret" in issued_document, issued_document
            wait(client, issued_document["operation"]["id"])
            doc_auth = (issued_document["credential"]["username"], issued_document["secret"])
            direct = httpx.get(f"https://caddy/couchdb/sl_{first}", auth=doc_auth, verify="/caddy-data/caddy/pki/authorities/local/root.crt")
            assert direct.status_code == 200, direct.text
            denied = httpx.get(f"https://caddy/couchdb/sl_{second}", auth=doc_auth, verify="/caddy-data/caddy/pki/authorities/local/root.crt")
            assert denied.status_code in {401, 403}, denied.text
            revoked_document = client.delete(
                f"/projects/{first}/capabilities/documents/credentials/{issued_document['credential']['id']}"
            ).json()
            wait(client, revoked_document["id"])
            denied_after_revoke = httpx.get(f"https://caddy/couchdb/sl_{first}", auth=doc_auth, verify="/caddy-data/caddy/pki/authorities/local/root.crt")
            assert denied_after_revoke.status_code in {401, 403}, denied_after_revoke.text

            issued = client.post(
                f"/projects/{first}/capabilities/postgresql/credentials",
                json={"label": "verification runtime", "access": "runtime"},
            ).json()
            assert "secret" in issued, issued
            wait(client, issued["operation"]["id"])
            migration = client.post(
                f"/projects/{first}/capabilities/postgresql/credentials",
                json={"label": "verification migration", "access": "migration"},
            ).json()
            assert migration["credential"]["access"] == "migration", migration
            wait(client, migration["operation"]["id"])
            with psycopg.connect(
                host=settings.postgres_internal_host, port=settings.postgres_internal_port, dbname=f"sl_{first}",
                user=migration["credential"]["username"], password=migration["secret"],
                sslmode="require",
            ) as connection:
                connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(f"sl_{first}_owner")))
                connection.execute("CREATE TABLE public.verification (id integer PRIMARY KEY)")
            with psycopg.connect(
                host=settings.postgres_internal_host, port=settings.postgres_internal_port, dbname=f"sl_{first}",
                user=issued["credential"]["username"], password=issued["secret"],
                sslmode="require",
            ) as connection:
                connection.execute("INSERT INTO public.verification (id) VALUES (1)")
                assert connection.execute("SELECT id FROM public.verification").fetchone() == (1,)
                try:
                    connection.execute("CREATE TABLE public.forbidden (id integer)")
                    raise AssertionError("Runtime role created a table")
                except psycopg.errors.InsufficientPrivilege:
                    connection.rollback()
            try:
                psycopg.connect(
                    host=settings.postgres_internal_host, port=settings.postgres_internal_port, dbname=f"sl_{second}",
                    user=issued["credential"]["username"], password=issued["secret"],
                    sslmode="require",
                )
                raise AssertionError("Cross-project PostgreSQL access succeeded")
            except psycopg.OperationalError:
                pass
            print("API and worker: two projects provisioned; PostgreSQL, S3, and CouchDB isolation verified")
        finally:
            for project_id, name, owner in projects:
                active["principal"] = owner
                for kind in ("documents", "object-storage", "postgresql"):
                    response = client.request(
                        "DELETE", f"/projects/{project_id}/capabilities/{kind}",
                        json={"confirm_name": name},
                    )
                    if response.status_code == 202:
                        wait(client, response.json()["id"])
            app.dependency_overrides.clear()


if __name__ == "__main__":
    main()
