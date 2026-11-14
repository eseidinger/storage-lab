"""OpenSearch index, tenant, role, and internal user administration."""

import httpx

from .settings import Settings


class OpenSearchAdapter:
    def __init__(self, settings: Settings):
        if not settings.opensearch_admin_url or not settings.opensearch_admin_password:
            raise RuntimeError("OpenSearch administration is not configured")
        self.settings = settings
        self.base = settings.opensearch_admin_url.rstrip("/")
        self.auth = ("admin", settings.opensearch_admin_password)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = httpx.request(method, f"{self.base}{path}", auth=self.auth, verify=False, timeout=30, **kwargs)
        if method == "DELETE" and response.status_code == 404:
            return response
        response.raise_for_status()
        return response

    @staticmethod
    def _name(project_id: str) -> str:
        if len(project_id) != 32 or not all(char in "0123456789abcdef" for char in project_id):
            raise ValueError("Invalid project ID")
        return f"sl_{project_id}"

    def provision(self, project_id: str) -> tuple[str, dict]:
        name = self._name(project_id)
        if not self._index_exists(name):
            self._request("PUT", f"/{name}", json={"settings": {"number_of_shards": 1, "number_of_replicas": 0}})
        self._request("PUT", f"/_plugins/_security/api/tenants/{name}", json={"description": f"Storage Lab project {project_id}"})
        self._request("PUT", f"/_plugins/_security/api/roles/{name}", json={
            "cluster_permissions": ["cluster_composite_ops"],
            "index_permissions": [{"index_patterns": [name, f"{name}-*"],
                                   "allowed_actions": ["crud", "create_index"]}],
            "tenant_permissions": [{"tenant_patterns": [name], "allowed_actions": ["kibana_all_write"]}],
        })
        return name, {"endpoint": self.settings.opensearch_public_url, "index": name,
                      "index_prefix": f"{name}-", "dashboard_tenant": name, "authentication": "basic"}

    def _index_exists(self, name: str) -> bool:
        response = httpx.request("HEAD", f"{self.base}/{name}", auth=self.auth, verify=False, timeout=10)
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    def issue(self, project_id: str, username: str, secret: str, access: str = "runtime") -> None:
        if access != "runtime":
            raise ValueError("OpenSearch credentials only support runtime access")
        name = self._name(project_id)
        self._request("PUT", f"/_plugins/_security/api/internalusers/{username}", json={
            "password": secret, "opendistro_security_roles": [name, "kibana_user"]})
        response = httpx.get(f"{self.base}/{name}/_count", auth=(username, secret), verify=False, timeout=10)
        response.raise_for_status()

    def revoke(self, project_id: str, username: str) -> None:
        self._request("DELETE", f"/_plugins/_security/api/internalusers/{username}")

    def delete(self, project_id: str) -> None:
        name = self._name(project_id)
        indices = httpx.get(f"{self.base}/_cat/indices/{name}*", params={"format": "json", "h": "index"},
                            auth=self.auth, verify=False, timeout=30)
        if indices.status_code != 404:
            indices.raise_for_status()
        for item in indices.json() if indices.status_code != 404 else []:
            index = item["index"]
            if index == name or index.startswith(f"{name}-"):
                self._request("DELETE", f"/{index}")
        self._request("DELETE", f"/_plugins/_security/api/roles/{name}")
        self._request("DELETE", f"/_plugins/_security/api/tenants/{name}")
