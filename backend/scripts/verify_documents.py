"""Exercise CouchDB users, project security, gateway filtering, and revocation."""

import time
from uuid import uuid4

import httpx

from storage_lab.adapters import CouchDBAdapter, resource_name
from storage_lab.settings import get_settings


def main() -> None:
    settings = get_settings()
    adapter = CouchDBAdapter(settings)
    first, second = uuid4().hex, uuid4().hex
    users = [f"sl_verify_{uuid4().hex[:20]}" for _ in range(2)]
    secrets = [uuid4().hex + uuid4().hex for _ in range(2)]
    browser_users = [f"sl_browser_{project[:20]}" for project in (first, second)]
    browser_secrets = [uuid4().hex + uuid4().hex for _ in range(2)]
    gateway = "https://caddy/couchdb"
    client = httpx.Client(verify="/caddy-data/caddy/pki/authorities/local/root.crt")
    try:
        for project in (first, second):
            adapter.provision(project)
        adapter.provision(first)
        for project, username, secret in zip((first, second), browser_users, browser_secrets):
            adapter.issue(project, username, secret)
        for project, username, secret in zip((first, second), users, secrets):
            adapter.issue(project, username, secret)
        adapter.issue(first, users[0], secrets[0])

        first_url = f"{gateway}/{resource_name(first)}"
        second_url = f"{gateway}/{resource_name(second)}"
        auth = (users[0], secrets[0])
        anonymous = client.get(first_url)
        assert anonymous.status_code in {401, 403}, (anonymous.status_code, anonymous.text)
        created = client.put(f"{first_url}/verification", auth=auth, json={"value": "first"})
        assert created.status_code == 201, (created.status_code, created.text)
        read = client.get(f"{first_url}/verification", auth=auth)
        assert read.status_code == 200 and read.json()["value"] == "first", read.text
        listed = client.get(f"{first_url}/_all_docs", auth=auth)
        assert listed.status_code == 200 and listed.json()["rows"][0]["id"] == "verification", listed.text
        denied = client.get(second_url, auth=auth)
        assert denied.status_code in {401, 403}, (denied.status_code, denied.text)
        blocked = client.get(f"{gateway}/_users", auth=auth)
        assert blocked.status_code == 403, (blocked.status_code, blocked.text)
        protected = client.put(
            f"{first_url}/_security", auth=auth,
            json={"admins": {"names": [], "roles": []}, "members": {"names": [], "roles": []}},
        )
        assert protected.status_code in {401, 403}, (protected.status_code, protected.text)
        encoded_security = client.put(
            f"{first_url}/%5Fsecurity", auth=auth,
            json={"admins": {"names": [], "roles": []}, "members": {"names": [], "roles": []}},
        )
        assert encoded_security.status_code in {401, 403}, (encoded_security.status_code, encoded_security.text)

        adapter.revoke(first, users[0])
        for _ in range(20):
            revoked = client.get(first_url, auth=auth)
            if revoked.status_code in {401, 403}:
                break
            time.sleep(0.2)
        else:
            raise AssertionError("Revoked CouchDB user retained project access")
    finally:
        for project, username in zip((first, second), users):
            adapter.revoke(project, username)
        for project, username in zip((first, second), browser_users):
            adapter.revoke(project, username)
        for project in (first, second):
            adapter.delete(project)

    adapter.provision(first)
    try:
        adapter.issue(first, browser_users[0], browser_secrets[0])
        restored = client.get(f"{gateway}/{resource_name(first)}", auth=(browser_users[0], browser_secrets[0]))
        assert restored.status_code == 200, (restored.status_code, restored.text)
    finally:
        adapter.revoke(first, browser_users[0])
        adapter.delete(first)
    client.close()
    print("CouchDB: project access, isolation, gateway restrictions, revocation, and reprovisioning verified")


if __name__ == "__main__":
    main()
