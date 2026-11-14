"""Project database and role administration for ClickHouse."""

import re

import httpx

from .settings import Settings


def identifier(value: str) -> str:
    if not re.fullmatch(r"sl_[a-z0-9_]+", value):
        raise ValueError("Invalid ClickHouse identifier")
    return f"`{value}`"


def literal(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


class ClickHouseAdapter:
    def __init__(self, settings: Settings):
        if not settings.clickhouse_admin_url or not settings.clickhouse_admin_password:
            raise RuntimeError("ClickHouse administration is not configured")
        self.settings = settings

    def _sql(self, statement: str) -> str:
        response = httpx.post(self.settings.clickhouse_admin_url, content=statement,
                              auth=("admin", self.settings.clickhouse_admin_password), timeout=30)
        response.raise_for_status()
        return response.text

    @staticmethod
    def _names(project_id: str) -> tuple[str, str]:
        if not re.fullmatch(r"[0-9a-f]{32}", project_id):
            raise ValueError("Invalid project ID")
        return f"sl_{project_id}", f"sl_{project_id}_role"

    def provision(self, project_id: str) -> tuple[str, dict]:
        database, role = self._names(project_id)
        self._sql(f"CREATE DATABASE IF NOT EXISTS {identifier(database)}")
        self._sql(f"CREATE ROLE IF NOT EXISTS {identifier(role)}")
        self._sql(f"GRANT SELECT, INSERT, CREATE TABLE, ALTER TABLE, DROP TABLE ON {identifier(database)}.* TO {identifier(role)}")
        self._sql(f"ALTER ROLE {identifier(role)} SETTINGS max_execution_time = 30, max_memory_usage = 1073741824, max_rows_to_read = 10000000, max_threads = 4")
        return database, {"endpoint": self.settings.clickhouse_public_url, "database": database,
                          "authentication": "basic", "query_timeout_seconds": 30}

    def issue(self, project_id: str, username: str, secret: str, access: str = "runtime") -> None:
        if access != "runtime":
            raise ValueError("ClickHouse credentials only support runtime access")
        database, role = self._names(project_id)
        user = identifier(username)
        self._sql(f"CREATE USER IF NOT EXISTS {user} IDENTIFIED WITH sha256_password BY {literal(secret)}")
        self._sql(f"ALTER USER {user} IDENTIFIED WITH sha256_password BY {literal(secret)}")
        self._sql(f"GRANT {identifier(role)} TO {user}")
        self._sql(f"ALTER USER {user} DEFAULT ROLE {identifier(role)}")
        response = httpx.post(self.settings.clickhouse_admin_url, content="SELECT currentDatabase()",
                              params={"database": database}, auth=(username, secret), timeout=10)
        response.raise_for_status()

    def revoke(self, project_id: str, username: str) -> None:
        self._sql(f"DROP USER IF EXISTS {identifier(username)}")

    def delete(self, project_id: str) -> None:
        database, role = self._names(project_id)
        self._sql(f"DROP DATABASE IF EXISTS {identifier(database)} SYNC")
        self._sql(f"DROP ROLE IF EXISTS {identifier(role)}")
