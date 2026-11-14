"""Service administration adapters. Only the worker should receive these credentials."""

import json
import time
from hashlib import sha256
from urllib.parse import quote, urlencode

import boto3
import httpx
import psycopg
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config
from botocore.credentials import Credentials
from botocore.exceptions import ClientError
from psycopg import sql
from psycopg.conninfo import make_conninfo

from .settings import Settings
from .valkey_adapter import ValkeyAdapter
from .clickhouse_adapter import ClickHouseAdapter


def resource_name(project_id: str) -> str:
    return f"sl_{project_id}"


class PostgreSQLAdapter:
    def __init__(self, settings: Settings):
        if not settings.postgres_admin_dsn:
            raise RuntimeError("PostgreSQL administration is not configured")
        self.settings = settings

    def _connect(self, dbname: str | None = None) -> psycopg.Connection:
        dsn = self.settings.postgres_admin_dsn
        if dbname:
            dsn = make_conninfo(dsn, dbname=dbname)
        return psycopg.connect(dsn, autocommit=True)

    def provision(self, project_id: str) -> tuple[str, dict]:
        dbname = resource_name(project_id)
        owner = f"{dbname}_owner"
        with self._connect() as conn:
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (owner,)).fetchone():
                conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(owner)))
            row = conn.execute(
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s", (dbname,)
            ).fetchone()
            if row is None:
                conn.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(dbname), sql.Identifier(owner)
                    )
                )
            elif row[0] != owner:
                raise RuntimeError("Existing project database has a different owner")
            conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(dbname)))
        with self._connect(dbname) as conn:
            conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        return dbname, {
            "host": self.settings.postgres_public_host,
            "port": self.settings.postgres_public_port,
            "database": dbname,
            "tls": True,
            "migration_role": owner,
        }

    def issue(self, project_id: str, username: str, secret: str, access: str = "runtime") -> None:
        if access not in {"runtime", "migration"}:
            raise ValueError("Unknown PostgreSQL credential access")
        dbname = resource_name(project_id)
        owner = f"{dbname}_owner"
        with self._connect() as conn:
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (username,)).fetchone():
                conn.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(username)))
            conn.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(username), sql.Literal(secret)
                )
            )
            conn.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(dbname), sql.Identifier(username)
                )
            )
            if access == "migration":
                conn.execute(
                    sql.SQL("GRANT {} TO {}").format(sql.Identifier(owner), sql.Identifier(username))
                )
        with self._connect(dbname) as conn:
            user = sql.Identifier(username)
            if access == "runtime":
                conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(user))
                conn.execute(
                    sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(user)
                )
                conn.execute(
                    sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(user)
                )
                conn.execute(
                    sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}").format(
                        sql.Identifier(owner), user
                    )
                )
                conn.execute(
                    sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {}").format(
                        sql.Identifier(owner), user
                    )
                )
        with psycopg.connect(
            host=self.settings.postgres_internal_host or self.settings.postgres_public_host,
            port=self.settings.postgres_internal_port or self.settings.postgres_public_port,
            dbname=dbname,
            user=username,
            password=secret,
            connect_timeout=5,
            sslmode="require",
        ) as conn:
            conn.execute("SELECT 1").fetchone()

    def revoke(self, project_id: str, username: str) -> None:
        dbname = resource_name(project_id)
        owner = f"{dbname}_owner"
        with self._connect() as conn:
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (username,)).fetchone():
                return
        with self._connect(dbname) as conn:
            user = sql.Identifier(username)
            conn.execute(
                sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public REVOKE ALL ON TABLES FROM {}").format(
                    sql.Identifier(owner), user
                )
            )
            conn.execute(
                sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {}").format(
                    sql.Identifier(owner), user
                )
            )
            conn.execute(sql.SQL("DROP OWNED BY {}").format(user))
        with self._connect() as conn:
            conn.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(
                sql.Identifier(dbname), sql.Identifier(username)
            ))
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(username)))

    def delete(self, project_id: str) -> None:
        dbname = resource_name(project_id)
        owner = f"{dbname}_owner"
        with self._connect() as conn:
            if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone():
                conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                    (dbname,),
                )
                conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(dbname)))
            if conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (owner,)).fetchone():
                conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(owner)))


class RustFSAdapter:
    def __init__(self, settings: Settings):
        if not all((settings.s3_endpoint_url, settings.s3_admin_access_key, settings.s3_admin_secret_key)):
            raise RuntimeError("RustFS administration is not configured")
        self.settings = settings
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_admin_access_key,
            aws_secret_access_key=settings.s3_admin_secret_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def _admin(self, method: str, path: str, query: dict | None = None, body: dict | None = None) -> None:
        url = f"{self.settings.s3_endpoint_url.rstrip('/')}/rustfs/admin/v3/{path}"
        if query:
            url += "?" + urlencode(query)
        data = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
        request = AWSRequest(
            method=method,
            url=url,
            data=data,
            headers={"Content-Type": "application/json", "x-amz-content-sha256": sha256(data).hexdigest()},
        )
        SigV4Auth(
            Credentials(self.settings.s3_admin_access_key, self.settings.s3_admin_secret_key),
            "s3",
            self.settings.s3_region,
        ).add_auth(request)
        response = httpx.request(method, url, content=data, headers=dict(request.headers), timeout=15)
        if method == "DELETE" and response.status_code == 404:
            return
        response.raise_for_status()

    def provision(self, project_id: str) -> tuple[str, dict]:
        bucket = resource_name(project_id).replace("_", "-")
        try:
            self.client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            params = {"Bucket": bucket}
            if self.settings.s3_region != "us-east-1":
                params["CreateBucketConfiguration"] = {"LocationConstraint": self.settings.s3_region}
            self.client.create_bucket(**params)
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetBucketLocation"], "Resource": [f"arn:aws:s3:::{bucket}"]},
                {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], "Resource": [f"arn:aws:s3:::{bucket}/*"]},
            ],
        }
        self._admin("PUT", "add-canned-policy", {"name": bucket}, policy)
        return bucket, {
            "endpoint": self.settings.s3_public_endpoint_url or self.settings.s3_endpoint_url,
            "bucket": bucket,
            "region": self.settings.s3_region,
            "addressing_style": "path",
        }

    def issue(self, project_id: str, username: str, secret: str, access: str = "runtime") -> None:
        if access != "runtime":
            raise ValueError("RustFS credentials only support runtime access")
        bucket = resource_name(project_id).replace("_", "-")
        self._admin("PUT", "add-user", {"accessKey": username}, {"secretKey": secret, "status": "enabled"})
        self._admin(
            "PUT",
            "set-user-or-group-policy",
            {"policyName": bucket, "userOrGroup": username, "isGroup": "false"},
        )
        client = boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint_url,
            region_name=self.settings.s3_region,
            aws_access_key_id=username,
            aws_secret_access_key=secret,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        client.list_objects_v2(Bucket=bucket, MaxKeys=1)

    def revoke(self, project_id: str, username: str) -> None:
        self._admin("DELETE", "remove-user", {"accessKey": username})

    def delete(self, project_id: str) -> None:
        bucket = resource_name(project_id).replace("_", "-")
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket):
                objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
                if objects:
                    self.client.delete_objects(Bucket=bucket, Delete={"Objects": objects})
            self.client.delete_bucket(Bucket=bucket)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchBucket"}:
                raise
        self._admin("DELETE", "remove-canned-policy", {"name": bucket})


class CouchDBAdapter:
    def __init__(self, settings: Settings):
        if not all((settings.couchdb_admin_url, settings.couchdb_admin_user, settings.couchdb_admin_password)):
            raise RuntimeError("CouchDB administration is not configured")
        self.settings = settings
        self.base_url = settings.couchdb_admin_url.rstrip("/")
        self.admin_auth = (settings.couchdb_admin_user, settings.couchdb_admin_password)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        return httpx.request(method, f"{self.base_url}{path}", auth=self.admin_auth, timeout=15, **kwargs)

    @staticmethod
    def _user_path(username: str) -> str:
        return f"/_users/org.couchdb.user:{quote(username, safe='')}"

    def _security(self, dbname: str) -> dict:
        response = self._request("GET", f"/{dbname}/_security")
        response.raise_for_status()
        return response.json()

    def _set_members(self, dbname: str, names: set[str]) -> None:
        if not names:
            raise RuntimeError("CouchDB database must have at least one member")
        response = self._request(
            "PUT",
            f"/{dbname}/_security",
            json={
                "admins": {"names": [], "roles": []},
                "members": {"names": sorted(names), "roles": []},
            },
        )
        response.raise_for_status()

    def provision(self, project_id: str) -> tuple[str, dict]:
        dbname = resource_name(project_id)
        response = self._request("PUT", f"/{dbname}")
        if response.status_code != 412:
            response.raise_for_status()
        security = self._security(dbname)
        names = set(security.get("members", {}).get("names") or [])
        names.add(f"sl_browser_{project_id[:20]}")
        self._set_members(dbname, names)
        return dbname, {
            "endpoint": f"{(self.settings.couchdb_public_url or self.base_url).rstrip('/')}/{dbname}",
            "database": dbname,
            "authentication": "basic",
        }

    def issue(self, project_id: str, username: str, secret: str, access: str = "runtime") -> None:
        if access != "runtime":
            raise ValueError("CouchDB credentials only support runtime access")
        dbname = resource_name(project_id)
        path = self._user_path(username)
        existing = self._request("GET", path)
        if existing.status_code not in {200, 404}:
            existing.raise_for_status()
        document = {"name": username, "password": secret, "roles": [], "type": "user"}
        if existing.status_code == 200:
            document["_rev"] = existing.json()["_rev"]
        created = self._request("PUT", path, json=document)
        created.raise_for_status()
        security = self._security(dbname)
        names = set(security.get("members", {}).get("names") or [])
        names.add(username)
        self._set_members(dbname, names)
        for attempt in range(10):
            verified = httpx.get(f"{self.base_url}/{dbname}", auth=(username, secret), timeout=10)
            if verified.status_code == 200:
                return
            if verified.status_code != 401 or attempt == 9:
                verified.raise_for_status()
            time.sleep(0.2)

    def revoke(self, project_id: str, username: str) -> None:
        dbname = resource_name(project_id)
        response = self._request("GET", f"/{dbname}/_security")
        if response.status_code == 200:
            names = set(response.json().get("members", {}).get("names") or [])
            if username in names and len(names) > 1:
                names.remove(username)
                self._set_members(dbname, names)
        elif response.status_code != 404:
            response.raise_for_status()
        path = self._user_path(username)
        user = self._request("GET", path)
        if user.status_code == 404:
            return
        user.raise_for_status()
        deleted = self._request("DELETE", path, params={"rev": user.json()["_rev"]})
        deleted.raise_for_status()

    def delete(self, project_id: str) -> None:
        response = self._request("DELETE", f"/{resource_name(project_id)}")
        if response.status_code != 404:
            response.raise_for_status()


def adapter_for(kind: str, settings: Settings):
    if kind == "postgresql":
        return PostgreSQLAdapter(settings)
    if kind == "object-storage":
        return RustFSAdapter(settings)
    if kind == "documents":
        return CouchDBAdapter(settings)
    if kind == "key-value":
        return ValkeyAdapter(settings)
    if kind == "analytics":
        return ClickHouseAdapter(settings)
    raise ValueError(f"Unsupported capability: {kind}")
