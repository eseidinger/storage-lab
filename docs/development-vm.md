# Local development VM

Ansible provisions an Ubuntu 24.04 VM with **16 vCPUs**, **32 GiB RAM**, and an **80 GiB virtual disk**. Docker Compose runs the API/React portal, provisioning worker, metadata PostgreSQL, application PostgreSQL, RustFS, CouchDB, and Caddy. Authentication uses an external OIDC realm such as the Platform Keycloak realm. Storage Lab no longer deploys a local Keycloak server or realm.

## Host requirements

- QEMU (`qemu-system-x86_64` and `qemu-img`), `cloud-localds`, OpenSSH, and Ansible Core. Docker Engine and Compose are installed inside the guest.
- At least 32 GiB of available memory and enough free storage for the VM disk and container volumes.
- Access to the Ubuntu 24.04 cloud image, Ubuntu package repositories, and container registries.
- KVM for practical performance. Without `/dev/kvm`, QEMU uses software emulation.

VM state, the SSH key, and generated deployment passwords are under ignored `.local/` directories. Forwarded host ports bind to `127.0.0.1` only.

## Provision and deploy

From the repository root:

```sh
ansible-playbook ansible/playbooks/dev-vm.yml
ansible-playbook -i ansible/inventory/dev.yml ansible/playbooks/app.yml
```

The first playbook creates and starts the VM. The second removes the former Podman containers and systemd services, removes host PostgreSQL, installs Docker and Compose, builds the shared API/worker image, initializes two PostgreSQL 18.7 containers, applies Alembic migrations, and starts the stack. It validates the Caddy configuration and checks the public routes. **Existing host PostgreSQL data, Podman volumes, and PostgreSQL 16 Compose volumes are not migrated.** PostgreSQL 18 uses new named volumes mounted at `/var/lib/postgresql`, matching the official image's data layout. Re-running `app.yml` preserves these PostgreSQL 18 volumes.

If the VM was started with the old forwarding rules, stop it using the PID in `.local/dev-vm/qemu.pid`, run `dev-vm.yml` again, then run `app.yml`. QEMU only reads port forwarding at startup. The current rules forward host 8080 to guest 443, host 9000 to guest 9443, and host 5433 to guest 5433. There is no Keycloak port forward.

The development inventory uses issuer `https://identity.eseidinger.de/realms/platform`, client ID `storage-lab-portal`, and API audience `storage-lab-api`. The external realm must allow `https://localhost:8080/auth/callback` as a redirect URI, `https://localhost:8080` as a post logout redirect URI, and `https://localhost:8080` as a web origin. See [Keycloak realm configuration](keycloak-realm.md). To use another realm, set both `STORAGE_LAB_OIDC_ISSUER` and `STORAGE_LAB_OIDC_JWKS_URL`; set `STORAGE_LAB_OIDC_CLIENT_ID` and `STORAGE_LAB_OIDC_AUDIENCE` if needed. The deployment does not create or change the external realm.

| Host URL or port | Service |
| --- | --- |
| `https://localhost:8080` | Portal and `/api` |
| `localhost:5433` | Application PostgreSQL with TLS |
| `https://localhost:9000` | S3 data gateway; administrative routes blocked |
| `https://localhost:8080/couchdb/<database>` | Project CouchDB data gateway; global routes blocked |
| `localhost:2222` | Guest SSH |

Metadata PostgreSQL, RustFS, CouchDB, and the worker have no direct host port. The API and worker are separate containers from the same image. Docker Engine itself is managed by the guest OS; Storage Lab services use Compose rather than custom systemd units.

## Platform Admin bootstrap

Global Platform Admin grants are stored in metadata PostgreSQL. After deployment, bootstrap the first admin using the user's OIDC `sub` claim:

```sh
sudo docker compose -f /opt/storage-lab/compose.yaml exec worker \
  python -m storage_lab.platform_admin \
  --issuer https://identity.eseidinger.de/realms/platform \
  --subject KEYCLOAK_USER_ID
```

Run this command in the VM. It is idempotent. The first admin can then manage grants in the portal. Keycloak roles are not used for Storage Lab authorization.

## Connect and verify

```sh
ssh -i .local/dev-vm/id_ed25519 -p 2222 \
  -o StrictHostKeyChecking=accept-new \
  -o UserKnownHostsFile=.local/dev-vm/known_hosts \
  lab@127.0.0.1
```

Inside the guest, inspect the stack with:

```sh
sudo docker compose -f /opt/storage-lab/compose.yaml ps
sudo docker compose -f /opt/storage-lab/compose.yaml logs --tail=100 app worker caddy
```

Caddy issues localhost certificates from its persistent internal CA. Copy its root certificate to the host and import it into the host OS and browser trust stores:

```sh
ssh -i .local/dev-vm/id_ed25519 -p 2222 lab@127.0.0.1 \
  'sudo docker compose -f /opt/storage-lab/compose.yaml cp caddy:/data/caddy/pki/authorities/local/root.crt /tmp/storage-lab-caddy-root.crt && sudo chmod 0644 /tmp/storage-lab-caddy-root.crt'
scp -i .local/dev-vm/id_ed25519 -P 2222 lab@127.0.0.1:/tmp/storage-lab-caddy-root.crt .local/dev-vm/caddy-root.crt
```

The application PostgreSQL certificate is `/opt/storage-lab/certs/postgres.crt` in the guest. Copy it with `scp` for host clients using `sslmode=verify-full` and `sslrootcert`. Its subject alternative names cover `localhost` and `127.0.0.1`.

Run the service isolation scripts inside the worker container:

```sh
sudo docker compose -f /opt/storage-lab/compose.yaml exec worker python /app/scripts/verify_dev_services.py
sudo docker compose -f /opt/storage-lab/compose.yaml exec worker python /app/scripts/verify_documents.py
sudo docker compose -f /opt/storage-lab/compose.yaml exec worker python /app/scripts/verify_end_to_end.py
```

The scripts exercise project isolation, credential revocation, API/worker operations, and gateway filtering. They use internal Docker DNS, require TLS for project PostgreSQL connections, and trust the Caddy internal CA for the gateway checks. Check the host-facing certificates and HTTPS routes separately:

```sh
curl --cacert .local/dev-vm/caddy-root.crt -i https://localhost:8080/api/health
curl --cacert .local/dev-vm/caddy-root.crt -i https://localhost:8080/auth/callback
curl --cacert .local/dev-vm/caddy-root.crt -i https://localhost:8080/couchdb/_all_dbs
curl --cacert .local/dev-vm/caddy-root.crt -i https://localhost:9000/rustfs/admin/v3/info
```

The first two routes return 200 and the administrative routes return 403. For local code checks on the host, run `backend/.venv/bin/pytest -q` and `npm run build` in `frontend/`.

To stop the VM, send a termination signal to the PID in `.local/dev-vm/qemu.pid`; run `dev-vm.yml` to restart it. A fresh VM disk is required for cloud-init changes because the instance ID is fixed.

For public deployment, use separate DNS names in `storage_lab_portal_host` and `storage_lab_s3_host`, route ports 80 and 443 to Caddy, and update the Keycloak client's exact HTTPS redirect and web origins. Caddy obtains and renews public ACME certificates. A public deployment also needs its own firewall rules, secret store, backup, restore, and monitoring setup.
