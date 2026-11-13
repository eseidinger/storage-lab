"""Exercise API, worker, PostgreSQL, and S3 in the development VM.

This script overrides only the external OIDC identity dependency because no
Developer Platform Keycloak configuration is shipped with the repository.
"""

import time
from uuid import uuid4

import psycopg
from psycopg import sql
from fastapi.testclient import TestClient

from storage_lab.api import app
from storage_lab.auth import Principal, current_principal


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
                for kind in ("postgresql", "object-storage"):
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
                host="localhost", port=5433, dbname=f"sl_{first}",
                user=migration["credential"]["username"], password=migration["secret"],
                sslmode="verify-full", sslrootcert="/etc/ssl/certs/storage-lab-pg.crt",
            ) as connection:
                connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(f"sl_{first}_owner")))
                connection.execute("CREATE TABLE public.verification (id integer PRIMARY KEY)")
            with psycopg.connect(
                host="localhost", port=5433, dbname=f"sl_{first}",
                user=issued["credential"]["username"], password=issued["secret"],
                sslmode="verify-full", sslrootcert="/etc/ssl/certs/storage-lab-pg.crt",
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
                    host="localhost", port=5433, dbname=f"sl_{second}",
                    user=issued["credential"]["username"], password=issued["secret"],
                    sslmode="verify-full", sslrootcert="/etc/ssl/certs/storage-lab-pg.crt",
                )
                raise AssertionError("Cross-project PostgreSQL access succeeded")
            except psycopg.OperationalError:
                pass
            print("API and worker: two projects provisioned; runtime/migration roles and object isolation verified")
        finally:
            for project_id, name, owner in projects:
                active["principal"] = owner
                for kind in ("object-storage", "postgresql"):
                    response = client.request(
                        "DELETE", f"/projects/{project_id}/capabilities/{kind}",
                        json={"confirm_name": name},
                    )
                    if response.status_code == 202:
                        wait(client, response.json()["id"])
            app.dependency_overrides.clear()


if __name__ == "__main__":
    main()
