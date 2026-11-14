import httpx

from storage_lab.hugegraph_adapter import HugeGraphAdapter
from storage_lab.settings import Settings


def test_hugegraph_project_target_and_permissions(monkeypatch):
    project = "a" * 32
    name = f"sl_{project}"
    calls = []
    objects = {"groups": [], "targets": [], "accesses": []}

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith(f"/graphs/{name}") and method == "GET":
            return httpx.Response(404, request=httpx.Request(method, url))
        plural = url.split("/")[-1]
        if method == "GET" and plural in objects:
            return httpx.Response(200, json={plural: objects[plural]}, request=httpx.Request(method, url))
        if method == "POST" and plural in objects:
            item = {**kwargs["json"], "id": f"{plural}-id"}
            objects[plural].append(item)
            return httpx.Response(201, json=item, request=httpx.Request(method, url))
        return httpx.Response(200, json={}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", fake_request)
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: fake_request("GET", url, **kwargs))
    adapter = HugeGraphAdapter(Settings(hugegraph_admin_url="http://hugegraph:8080", hugegraph_admin_password="secret"))
    adapter.provision(project)
    graph = next(kwargs["json"] for method, url, kwargs in calls if method == "POST" and url.endswith(f"/graphs/{name}"))
    assert graph["gremlin.graph"].endswith("HugeFactoryAuthProxy")
    assert graph["store"] == name
    assert objects["targets"][0]["target_graph"] == name
    assert {item["access_permission"] for item in objects["accesses"]} == {"READ", "WRITE", "DELETE", "EXECUTE"}
