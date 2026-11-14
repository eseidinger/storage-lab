"""Exercise project isolation against the deployed development services.

Run only in a disposable development environment with worker settings loaded.
"""

from uuid import uuid4

import boto3
import httpx
import psycopg
from botocore.config import Config
from botocore.exceptions import ClientError

from storage_lab.adapters import PostgreSQLAdapter, RustFSAdapter
from storage_lab.settings import get_settings


def main() -> None:
    settings = get_settings()
    first, second = uuid4().hex, uuid4().hex
    pg = PostgreSQLAdapter(settings)
    s3 = RustFSAdapter(settings)
    users = [f"sl_verify_{uuid4().hex[:20]}" for _ in range(4)]
    secrets = [uuid4().hex + uuid4().hex for _ in range(4)]
    created_pg: list[str] = []
    created_s3: list[str] = []
    try:
        for project in (first, second):
            pg.provision(project)
            created_pg.append(project)
            created_s3.append(project)
            try:
                s3.provision(project)
            except httpx.HTTPStatusError as exc:
                print(f"RustFS policy response: HTTP {exc.response.status_code} {exc.response.text[:300]}")
                raise
        pg.issue(first, users[0], secrets[0])
        pg.issue(second, users[1], secrets[1])
        with psycopg.connect(host=settings.postgres_internal_host, port=settings.postgres_internal_port, dbname=f"sl_{first}", user=users[0], password=secrets[0], sslmode="require") as conn:
            assert conn.execute("SELECT current_database()").fetchone()[0] == f"sl_{first}"
        try:
            psycopg.connect(host=settings.postgres_internal_host, port=settings.postgres_internal_port, dbname=f"sl_{second}", user=users[0], password=secrets[0], sslmode="require")
            raise AssertionError("PostgreSQL cross-project connection succeeded")
        except psycopg.OperationalError:
            pass
        print("PostgreSQL: project access works and cross-project access is denied")

        s3.issue(first, users[2], secrets[2])
        s3.issue(second, users[3], secrets[3])
        client = boto3.client(
            "s3", endpoint_url=settings.s3_endpoint_url, region_name=settings.s3_region,
            aws_access_key_id=users[2], aws_secret_access_key=secrets[2],
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        first_bucket = f"sl-{first}"
        second_bucket = f"sl-{second}"
        client.put_object(Bucket=first_bucket, Key="verification.txt", Body=b"ok")
        assert client.get_object(Bucket=first_bucket, Key="verification.txt")["Body"].read() == b"ok"
        try:
            client.list_objects_v2(Bucket=second_bucket)
            raise AssertionError("S3 cross-project list succeeded")
        except ClientError as exc:
            assert exc.response["Error"]["Code"] in {"AccessDenied", "403"}
        print("S3: project access works and cross-project access is denied")
    finally:
        for project, username in zip((first, second), users[:2]):
            if project in created_pg:
                pg.revoke(project, username)
        for project, username in zip((first, second), users[2:]):
            if project in created_s3:
                s3.revoke(project, username)
        for project in created_pg:
            pg.delete(project)
        for project in created_s3:
            s3.delete(project)


if __name__ == "__main__":
    main()
