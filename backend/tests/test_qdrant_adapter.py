import httpx
import jwt

from storage_lab.qdrant_adapter import QdrantAdapter
from storage_lab.settings import Settings


def test_qdrant_jwt_is_collection_scoped_and_revocable(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        body = {"result": {"exists": False}} if url.endswith("/exists") else {}
        return httpx.Response(200, json=body, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", fake_request)
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: fake_request("GET", url, **kwargs))
    adapter = QdrantAdapter(Settings(qdrant_admin_url="http://qdrant:6333", qdrant_api_key="a" * 64))
    project = "a" * 32
    adapter.provision(project, vector_size=768, distance="Dot")
    collection_create = next(call for call in calls if call[0] == "PUT" and call[1].endswith(f"/collections/sl_{project}"))
    assert collection_create[2]["json"]["vectors"] == {"size": 768, "distance": "Dot"}
    token = adapter.issue(project, "sl_workload", "seed")
    payload = jwt.decode(token, "a" * 64, algorithms=["HS256"])
    assert payload["access"] == [{"collection": f"sl_{project}", "access": "rw"}]
    assert payload["value_exists"]["matches"] == [{"key": "credential_id", "value": "sl_workload"}]
    assert calls[-2][2]["json"]["points"][0]["payload"]["credential_id"] == "sl_workload"
    adapter.revoke(project, "sl_workload")
    assert calls[-1][1].endswith("/points/delete?wait=true")
