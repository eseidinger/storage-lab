# Local development VM

Ansible provisions an Ubuntu 24.04 VM with **16 vCPUs**, **32 GiB RAM**, and an **80 GiB virtual disk**. The application playbook installs and runs the API, worker, React portal, two PostgreSQL clusters, RustFS, local Keycloak, and Nginx.

## Host requirements

- QEMU (`qemu-system-x86_64` and `qemu-img`), `cloud-localds`, OpenSSH, Ansible Core, Node.js, and npm.
- At least 32 GiB of available memory and enough free storage for the virtual disk's used contents.
- Access to the Ubuntu 24.04 cloud image on first provisioning and to package/container registries during initial deployment.
- KVM for practical performance. Without `/dev/kvm`, QEMU uses software emulation and starts much more slowly.

VM state, the disk, SSH key, and generated deployment passwords are under ignored `.local/` directories. Host-forwarded ports bind to `127.0.0.1` only.

## Provision and deploy

From the repository root:

```sh
npm ci --prefix frontend
ansible-playbook ansible/playbooks/dev-vm.yml
ansible-playbook -i ansible/inventory/dev.yml ansible/playbooks/app.yml
```

The first playbook downloads the cloud image, creates an independent QCOW2 disk, injects a dedicated SSH key with cloud-init, starts QEMU, and waits for SSH. `app.yml` imports `deploy.yml`, then configures data services, runs Alembic migrations, installs API and worker systemd units, builds the portal, and deploys Nginx. Re-running the playbooks preserves the VM disk, databases, and RustFS volume. Realm JSON import applies only when the local Keycloak realm is first created; later changes to users or clients need a Keycloak admin update or a fresh development realm.

| Host URL or port | Service |
| --- | --- |
| `http://localhost:8080` | Portal and `/api` |
| `http://localhost:8081` | Local Keycloak |
| `localhost:5433` | Application PostgreSQL with TLS |
| `http://localhost:9000` | Public S3 data gateway; admin routes blocked |
| `localhost:2222` | Guest SSH |

The local Keycloak realm is `storage-lab`; its portal client is `storage-lab-portal`, its API audience is `storage-lab-api`, and its sample user is `lab`. Read the generated password from `.local/deploy/keycloak-user-password`. The local Keycloak admin password is in `.local/deploy/keycloak-admin-password`. These files are private development secrets and must not be committed.

To use an external issuer, set all four variables before the application playbook: `STORAGE_LAB_OIDC_ISSUER`, `STORAGE_LAB_OIDC_JWKS_URL`, `STORAGE_LAB_OIDC_AUDIENCE`, and `STORAGE_LAB_OIDC_CLIENT_ID`. Configure the external portal client for code flow with PKCE and the local callback URL. The playbook requires a JWKS URL when an external issuer is selected.

## Connect and verify

```sh
ssh -i .local/dev-vm/id_ed25519 -p 2222 \
  -o StrictHostKeyChecking=accept-new \
  -o UserKnownHostsFile=.local/dev-vm/known_hosts \
  lab@127.0.0.1
```

The PostgreSQL server certificate is `/etc/ssl/certs/storage-lab-pg.crt` in the guest. Copy it to the host with `scp` through port 2222 when using `sslmode=verify-full` from host tools. Its subject alternative names cover `localhost` and `127.0.0.1` only. The certificate is self-signed and valid for one year; it is for local development.

On the host, initialize the backend test environment and run the local checks:

```sh
cd backend
uv sync --extra test
.venv/bin/pytest -q
cd ../frontend
npm run build
```

The service verification scripts run against the development VM. From the guest, with worker settings loaded, run:

```sh
sudo -u storage-lab-worker bash -c 'set -a; source /etc/storage-lab/worker.env; export PYTHONPATH=/opt/storage-lab/backend/src; cd /opt/storage-lab/backend; /opt/storage-lab/venv/bin/python scripts/verify_dev_services.py'
sudo -u storage-lab-worker bash -c 'set -a; source /etc/storage-lab/worker.env; export PYTHONPATH=/opt/storage-lab/backend/src; cd /opt/storage-lab/backend; /opt/storage-lab/venv/bin/python scripts/verify_end_to_end.py'
```

The first script checks direct PostgreSQL and S3 project isolation. The second exercises API, worker, PostgreSQL migration/runtime access, object operations, cross-project denial, and cleanup with two temporary projects. On the host, `backend/.venv/bin/python backend/scripts/verify_oidc.py` verifies a real local Keycloak token against the public API. That OIDC script creates and removes a temporary password-grant client only for the test; the portal itself uses Authorization Code with PKCE. `curl -i http://localhost:8080/api/health` checks the HTTP route, and `curl -i http://localhost:9000/rustfs/admin/v3/info` should return 403.

To stop the VM, send a termination signal to the PID in `.local/dev-vm/qemu.pid`. Run the first playbook again to restart it. Changes to cloud-init data after first boot require a fresh VM disk because the development VM uses a fixed cloud-init instance ID.

This inventory and its HTTP endpoints are local-development settings. A shared or production deployment needs its own inventory, DNS, trusted TLS, firewall rules, secret store, backups, and restore procedure.
