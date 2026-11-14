import httpx

from storage_lab.clickhouse_adapter import ClickHouseAdapter, identifier
from storage_lab.settings import Settings


def test_clickhouse_project_role_and_user_are_scoped(monkeypatch):
    statements = []

    def fake_post(url, *, content, auth, **kwargs):
        statements.append((content, auth))
        return httpx.Response(200, text="1", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    adapter = ClickHouseAdapter(Settings(clickhouse_admin_url="http://clickhouse:8123", clickhouse_admin_password="secret"))
    project = "a" * 32
    adapter.provision(project)
    adapter.issue(project, "sl_workload", "workload-secret")
    role = f"`sl_{project}_role`"
    assert any(f"ON `sl_{project}`.* TO {role}" in sql for sql, _ in statements)
    assert any("max_memory_usage" in sql and "max_execution_time" in sql for sql, _ in statements)
    assert any(f"GRANT {role} TO `sl_workload`" in sql for sql, _ in statements)
    assert statements[-1][1] == ("sl_workload", "workload-secret")
    assert all(auth == ("admin", "secret") for _, auth in statements[:-1])


def test_clickhouse_identifier_rejects_sql_injection():
    for value in ("sl_x`; DROP DATABASE default; --", "sl_x.y", "default"):
        try:
            identifier(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Accepted {value!r}")
