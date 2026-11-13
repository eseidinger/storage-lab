from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from storage_lab.auth import current_principal
from storage_lab.settings import Settings


def test_oidc_signature_issuer_audience_and_expiry(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Key:
        key = private_key.public_key()

    class Client:
        def get_signing_key_from_jwt(self, token):
            return Key()

    monkeypatch.setattr("storage_lab.auth.jwks_client", lambda url: Client())
    monkeypatch.setattr(
        "storage_lab.auth.get_settings",
        lambda: Settings(
            oidc_issuer="https://idp.example/realms/dev",
            oidc_audience="storage-lab-api",
            oidc_jwks_url="https://idp.example/keys",
        ),
    )

    def verify(**changes):
        claims = {
            "iss": "https://idp.example/realms/dev",
            "aud": "storage-lab-api",
            "sub": "alice",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            **changes,
        }
        token = jwt.encode(claims, private_key, algorithm="RS256")
        return current_principal(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))

    assert verify().subject == "alice"
    for changes in (
        {"iss": "https://other.example/realms/dev"},
        {"aud": "another-api"},
        {"exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
    ):
        with pytest.raises(HTTPException) as error:
            verify(**changes)
        assert error.value.status_code == 401

    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        {"iss": "https://idp.example/realms/dev", "aud": "storage-lab-api", "sub": "alice", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        other_key,
        algorithm="RS256",
    )
    with pytest.raises(HTTPException) as error:
        current_principal(HTTPAuthorizationCredentials(scheme="Bearer", credentials=forged))
    assert error.value.status_code == 401
