"""HugeGraph graph, target, group, and workload administration."""

from urllib.parse import quote

import httpx

from .settings import Settings


class HugeGraphAdapter:
    AUTH = "/graphspaces/DEFAULT/auth"
    GRAPHS = "/graphspaces/DEFAULT/graphs"

    def __init__(self, settings: Settings):
        if not settings.hugegraph_admin_url or not settings.hugegraph_admin_password:
            raise RuntimeError("HugeGraph administration is not configured")
        self.settings = settings
        self.base = settings.hugegraph_admin_url.rstrip("/")
        self.auth = ("admin", settings.hugegraph_admin_password)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = httpx.request(method, f"{self.base}{path}", auth=self.auth, timeout=30, **kwargs)
        if method == "DELETE" and response.status_code == 404:
            return response
        response.raise_for_status()
        return response

    def _find(self, plural: str, key: str, value: str) -> dict | None:
        objects = self._request("GET", f"{self.AUTH}/{plural}", params={"limit": 10000}).json().get(plural, [])
        return next((item for item in objects if item.get(key) == value), None)

    def _ensure(self, plural: str, key: str, value: str, body: dict) -> dict:
        found = self._find(plural, key, value)
        return found or self._request("POST", f"{self.AUTH}/{plural}", json=body).json()

    def provision(self, project_id: str) -> tuple[str, dict]:
        name = f"sl_{project_id}"
        graph = httpx.get(f"{self.base}{self.GRAPHS}/{name}", auth=self.auth, timeout=10)
        if graph.status_code == 404:
            self._request("POST", f"{self.GRAPHS}/{name}", json={
                "gremlin.graph": "org.apache.hugegraph.auth.HugeFactoryAuthProxy",
                "backend": "rocksdb", "serializer": "binary", "store": name,
                "rocksdb.data_path": f"./rocksdb-data/{name}",
                "rocksdb.wal_path": f"./rocksdb-wal/{name}",
            })
        else:
            graph.raise_for_status()
        group = self._ensure("groups", "group_name", name, {"group_name": name, "group_description": name})
        target = self._ensure("targets", "target_name", name, {
            "target_name": name, "target_graph": name, "target_url": "hugegraph:8080",
            "target_resources": [{"type": "ALL"}],
        })
        existing = self._request("GET", f"{self.AUTH}/accesses", params={"limit": 10000}).json().get("accesses", [])
        for permission in ("READ", "WRITE", "DELETE", "EXECUTE"):
            if not any(item.get("group") == group["id"] and item.get("target") == target["id"]
                       and item.get("access_permission") == permission for item in existing):
                self._request("POST", f"{self.AUTH}/accesses", json={
                    "group": group["id"], "target": target["id"], "access_permission": permission,
                })
        return name, {"endpoint": self.settings.hugegraph_public_url, "graph": name,
                      "authentication": "basic"}

    def issue(self, project_id: str, username: str, secret: str, access: str = "runtime") -> None:
        if access != "runtime":
            raise ValueError("HugeGraph credentials only support runtime access")
        group = self._find("groups", "group_name", f"sl_{project_id}")
        if group is None:
            raise RuntimeError("HugeGraph project group is missing")
        user = self._find("users", "user_name", username)
        if user is None:
            self._request("POST", f"{self.AUTH}/users", json={"user_name": username, "user_password": secret})
        else:
            self._request("PUT", f"{self.AUTH}/users/{quote(str(user['id']), safe='')}",
                          json={"user_name": username, "user_password": secret})
        belongs = self._request("GET", f"{self.AUTH}/belongs", params={"limit": 10000}).json().get("belongs", [])
        if not any(item.get("user") == username and item.get("group") == group["id"] for item in belongs):
            self._request("POST", f"{self.AUTH}/belongs", json={"user": username, "group": group["id"]})
        response = httpx.get(f"{self.base}{self.GRAPHS}/sl_{project_id}", auth=(username, secret), timeout=10)
        response.raise_for_status()

    def revoke(self, project_id: str, username: str) -> None:
        user = self._find("users", "user_name", username)
        if user is not None:
            belongs = self._request("GET", f"{self.AUTH}/belongs", params={"limit": 10000}).json().get("belongs", [])
            for item in belongs:
                if item.get("user") == username:
                    self._request("DELETE", f"{self.AUTH}/belongs/{quote(str(item['id']), safe='')}")
            self._request("DELETE", f"{self.AUTH}/users/{quote(str(user['id']), safe='')}")

    def delete(self, project_id: str) -> None:
        name = f"sl_{project_id}"
        group = self._find("groups", "group_name", name)
        target = self._find("targets", "target_name", name)
        if group or target:
            accesses = self._request("GET", f"{self.AUTH}/accesses", params={"limit": 10000}).json().get("accesses", [])
            for item in accesses:
                if item.get("group") == (group or {}).get("id") or item.get("target") == (target or {}).get("id"):
                    self._request("DELETE", f"{self.AUTH}/accesses/{quote(str(item['id']), safe='')}")
        if target:
            self._request("DELETE", f"{self.AUTH}/targets/{quote(str(target['id']), safe='')}")
        if group:
            belongs = self._request("GET", f"{self.AUTH}/belongs", params={"limit": 10000}).json().get("belongs", [])
            for item in belongs:
                if item.get("group") == group["id"]:
                    self._request("DELETE", f"{self.AUTH}/belongs/{quote(str(item['id']), safe='')}")
            self._request("DELETE", f"{self.AUTH}/groups/{quote(str(group['id']), safe='')}")
        self._request("DELETE", f"{self.GRAPHS}/{name}", params={"confirm_message": "I'm sure to drop the graph"})
