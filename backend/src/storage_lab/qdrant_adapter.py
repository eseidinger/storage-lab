"""Collection-scoped Qdrant JWTs with point-backed revocation."""

from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

import httpx
import jwt

from .settings import Settings


class QdrantAdapter:
    TOKEN_COLLECTION = "storage_lab_credential_registry"

    def __init__(self, settings: Settings):
        if not settings.qdrant_admin_url or not settings.qdrant_api_key:
            raise RuntimeError("Qdrant administration is not configured")
        self.settings = settings
        self.base = settings.qdrant_admin_url.rstrip("/")

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = httpx.request(method, f"{self.base}{path}", headers={"api-key": self.settings.qdrant_api_key}, timeout=20, **kwargs)
        response.raise_for_status()
        return response

    @staticmethod
    def _point_id(username: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"storage-lab:qdrant:{username}"))

    def provision(self, project_id: str) -> tuple[str, dict]:
        name = f"sl_{project_id}"
        if self._request("GET", f"/collections/{self.TOKEN_COLLECTION}/exists").json().get("result", {}).get("exists") is False:
            self._request("PUT", f"/collections/{self.TOKEN_COLLECTION}", json={"vectors": {"size": 1, "distance": "Dot"}})
        if self._request("GET", f"/collections/{name}/exists").json().get("result", {}).get("exists") is False:
            self._request("PUT", f"/collections/{name}", json={"vectors": {"size": 1536, "distance": "Cosine"}})
        return name, {"endpoint": self.settings.qdrant_public_url, "collection": name,
                      "vector_size": 1536, "distance": "Cosine", "authentication": "api-key"}

    def issue(self, project_id: str, username: str, secret: str, access: str = "runtime") -> str:
        if access != "runtime":
            raise ValueError("Qdrant credentials only support runtime access")
        name = f"sl_{project_id}"
        self._request("PUT", f"/collections/{self.TOKEN_COLLECTION}/points?wait=true", json={"points": [
            {"id": self._point_id(username), "vector": [1.0], "payload": {"credential_id": username}}
        ]})
        token = jwt.encode({"access": [{"collection": name, "access": "rw"}],
                            "value_exists": {"collection": self.TOKEN_COLLECTION,
                                             "matches": [{"key": "credential_id", "value": username}]},
                            "jti": sha256(secret.encode()).hexdigest()},
                           self.settings.qdrant_api_key, algorithm="HS256")
        response = httpx.get(f"{self.base}/collections/{name}", headers={"api-key": token}, timeout=10)
        response.raise_for_status()
        return token

    def revoke(self, project_id: str, username: str) -> None:
        self._request("POST", f"/collections/{self.TOKEN_COLLECTION}/points/delete?wait=true",
                      json={"points": [self._point_id(username)]})

    def delete(self, project_id: str) -> None:
        response = httpx.delete(f"{self.base}/collections/sl_{project_id}",
                                headers={"api-key": self.settings.qdrant_api_key}, timeout=20)
        if response.status_code != 404:
            response.raise_for_status()
