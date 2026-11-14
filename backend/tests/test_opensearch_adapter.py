import httpx

from storage_lab.opensearch_adapter import OpenSearchAdapter
from storage_lab.settings import Settings


def test_opensearch_role_scopes_indices_and_tenant(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(404 if method == "HEAD" else 200, json={}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", fake_request)
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: httpx.Response(200, json={"count": 0}, request=httpx.Request("GET", url)))
    adapter = OpenSearchAdapter(Settings(opensearch_admin_url="https://opensearch:9200", opensearch_admin_password="secret"))
    project = "a" * 32
    adapter.provision(project)
    role = next(kwargs["json"] for method, url, kwargs in calls if url.endswith(f"/roles/sl_{project}"))
    assert role["index_permissions"][0]["index_patterns"] == [f"sl_{project}", f"sl_{project}-*"]
    assert role["tenant_permissions"][0]["tenant_patterns"] == [f"sl_{project}"]
    adapter.issue(project, "sl_workload", "password")
    user = next(kwargs["json"] for method, url, kwargs in calls if url.endswith("/internalusers/sl_workload"))
    assert f"sl_{project}" in user["opendistro_security_roles"]
