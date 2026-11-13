"""Check the local development Keycloak realm against the public API.

Creates a temporary password-grant client only for this automated check and
deletes it afterward. Browser sign-in continues to use Authorization Code/PKCE.
"""

from pathlib import Path
from uuid import uuid4

import httpx
import jwt


ROOT = Path(__file__).resolve().parents[2]
SECRETS = ROOT / ".local" / "deploy"
KEYCLOAK = "http://127.0.0.1:8081"
API = "http://127.0.0.1:8080/api"


def main() -> None:
    admin_password = (SECRETS / "keycloak-admin-password").read_text().strip()
    user_password = (SECRETS / "keycloak-user-password").read_text().strip()
    with httpx.Client(timeout=20) as client:
        admin = client.post(
            f"{KEYCLOAK}/realms/master/protocol/openid-connect/token",
            data={"grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": admin_password},
        )
        admin.raise_for_status()
        headers = {"Authorization": f"Bearer {admin.json()['access_token']}"}
        client_id = f"storage-lab-verifier-{uuid4().hex[:8]}"
        created = client.post(
            f"{KEYCLOAK}/admin/realms/storage-lab/clients",
            headers=headers,
            json={
                "clientId": client_id,
                "enabled": True,
                "publicClient": True,
                "standardFlowEnabled": False,
                "directAccessGrantsEnabled": True,
                "protocolMappers": [{
                    "name": "api-audience",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-audience-mapper",
                    "config": {"included.custom.audience": "storage-lab-api", "access.token.claim": "true", "id.token.claim": "false"},
                }],
            },
        )
        created.raise_for_status()
        temporary_id = created.headers["Location"].rsplit("/", 1)[-1]
        try:
            token_response = client.post(
                f"{KEYCLOAK}/realms/storage-lab/protocol/openid-connect/token",
                data={"grant_type": "password", "client_id": client_id, "username": "lab", "password": user_password},
            )
            if token_response.is_error:
                raise RuntimeError(f"Keycloak token request failed: {token_response.status_code} {token_response.text}")
            token = token_response.json()["access_token"]
            claims = jwt.decode(token, options={"verify_signature": False})
            assert claims["iss"] == "http://localhost:8081/realms/storage-lab"
            assert "storage-lab-api" in claims["aud"]
            response = client.get(f"{API}/projects", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200, response.text
            print("Keycloak token accepted by API with configured issuer and audience")
        finally:
            removed = client.delete(
                f"{KEYCLOAK}/admin/realms/storage-lab/clients/{temporary_id}", headers=headers
            )
            removed.raise_for_status()


if __name__ == "__main__":
    main()
