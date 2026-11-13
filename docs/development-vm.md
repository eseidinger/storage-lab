# Local development VM

Ansible provisions an Ubuntu 24.04 VM with **16 vCPUs**, **32 GiB RAM**, and an **80 GiB virtual disk**. The application playbook installs and runs the API, worker, React portal, two PostgreSQL clusters, RustFS, and Nginx. The development inventory uses the Platform Keycloak realm; a local realm is optional.

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

The first playbook downloads the cloud image, creates an independent QCOW2 disk, injects a dedicated SSH key with cloud-init, starts QEMU, and waits for SSH. `app.yml` imports `deploy.yml`, then configures data services, runs Alembic migrations, installs API and worker systemd units, builds the portal, and deploys Nginx. Re-running the playbooks preserves the VM disk, databases, and RustFS volume. The default OIDC values come from `ansible/inventory/dev.yml`: issuer `https://identity.eseidinger.de/realms/platform`, client `storage-lab-portal`, and API audience `storage-lab-api`.

| Host URL or port | Service |
| --- | --- |
| `http://localhost:8080` | Portal and `/api` |
| `http://localhost:8081` | Optional local Keycloak, only when selected |
| `localhost:5433` | Application PostgreSQL with TLS |
| `http://localhost:9000` | Public S3 data gateway; admin routes blocked |
| `localhost:2222` | Guest SSH |

To use the optional local Keycloak realm, run `STORAGE_LAB_USE_LOCAL_KEYCLOAK=true ansible-playbook -i ansible/inventory/dev.yml ansible/playbooks/app.yml`. Its realm is `storage-lab`, portal client is `storage-lab-portal`, API audience is `storage-lab-api`, and sample user is `lab`. Read the generated password from `.local/deploy/keycloak-user-password`. The local admin password is in `.local/deploy/keycloak-admin-password`. These files are private development secrets and must not be committed. Realm JSON import applies only when the local realm is first created; later changes need a Keycloak admin update or a fresh development realm.

To override the inventory's external issuer, set both `STORAGE_LAB_OIDC_ISSUER` and `STORAGE_LAB_OIDC_JWKS_URL` before running the application playbook. Set `STORAGE_LAB_OIDC_AUDIENCE` and `STORAGE_LAB_OIDC_CLIENT_ID` if those differ as well. Configure the portal client for code flow with PKCE, callback URL `http://localhost:8080/auth/callback`, and an access-token audience matching the API setting.

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

The first script checks direct PostgreSQL and S3 project isolation. The second exercises API, worker, PostgreSQL migration/runtime access, object operations, cross-project denial, and cleanup with two temporary projects. If the optional local Keycloak is running, `backend/.venv/bin/python backend/scripts/verify_oidc.py` verifies a real local token against the public API; it creates and removes a temporary password-grant client only for the test. The portal itself uses Authorization Code with PKCE. `curl -i http://localhost:8080/api/health` checks the HTTP route, and `curl -i http://localhost:9000/rustfs/admin/v3/info` should return 403.

To stop the VM, send a termination signal to the PID in `.local/dev-vm/qemu.pid`. Run the first playbook again to restart it. Changes to cloud-init data after first boot require a fresh VM disk because the development VM uses a fixed cloud-init instance ID.

This inventory and its HTTP endpoints are local-development settings. A shared or production deployment needs its own inventory, DNS, trusted TLS, firewall rules, secret store, backups, and restore procedure.
