# Local development VM

Ansible provisions an Ubuntu 24.04 VM with **16 vCPUs**, **32 GiB RAM**, and an **80 GiB virtual disk**. The application playbook installs and runs the combined API/React portal image, worker, two PostgreSQL clusters, RustFS, CouchDB, and Caddy. The development inventory uses the Platform Keycloak realm; a local realm is optional.

## Host requirements

- QEMU (`qemu-system-x86_64` and `qemu-img`), `cloud-localds`, OpenSSH, and Ansible Core. Podman builds the app image in the guest.
- At least 32 GiB of available memory and enough free storage for the virtual disk's used contents.
- Access to the Ubuntu 24.04 cloud image on first provisioning and to package/container registries during initial deployment.
- KVM for practical performance. Without `/dev/kvm`, QEMU uses software emulation and starts much more slowly.

VM state, the disk, SSH key, and generated deployment passwords are under ignored `.local/` directories. Host-forwarded ports bind to `127.0.0.1` only.

## Provision and deploy

From the repository root:

```sh
ansible-playbook ansible/playbooks/dev-vm.yml
ansible-playbook -i ansible/inventory/dev.yml ansible/playbooks/app.yml
```

The first playbook downloads the cloud image, creates an independent QCOW2 disk, injects a dedicated SSH key with cloud-init, starts QEMU, and waits for SSH. `app.yml` imports `deploy.yml`, then configures data services, runs Alembic migrations, builds the API/portal image, installs the app and worker services, and deploys Caddy. Re-running the playbooks preserves the VM disk, databases, and RustFS/CouchDB volumes. The default OIDC values come from `ansible/inventory/dev.yml`: issuer `https://identity.eseidinger.de/realms/platform`, client `storage-lab-portal`, and API audience `storage-lab-api`.

When upgrading a VM started before the HTTPS change, stop QEMU using the PID in `.local/dev-vm/qemu.pid`, then run `dev-vm.yml` again before `app.yml`. QEMU reads port forwarding only at startup; the new rules forward host 8080 to guest 443, host 9000 to guest 9443, and host 8081 to guest 9444. Keep the VM disk and deployment secrets. Update the external Keycloak portal client to allow `https://localhost:8080/auth/callback` as a redirect, `https://localhost:8080` as a post logout redirect, and `https://localhost:8080` as a web origin before signing in.

For the required settings of an existing external realm, see [Keycloak realm configuration](keycloak-realm.md).

| Host URL or port | Service |
| --- | --- |
| `https://localhost:8080` | Portal and `/api` |
| `https://localhost:8081` | Optional local Keycloak, only when selected |
| `localhost:5433` | Application PostgreSQL with TLS |
| `https://localhost:9000` | Public S3 data gateway; admin routes blocked |
| `https://localhost:8080/couchdb/<database>` | Project CouchDB data gateway; global routes blocked |
| `localhost:2222` | Guest SSH |

To use the optional local Keycloak realm, run `STORAGE_LAB_USE_LOCAL_KEYCLOAK=true ansible-playbook -i ansible/inventory/dev.yml ansible/playbooks/app.yml`. Its realm is `storage-lab`, portal client is `storage-lab-portal`, API audience is `storage-lab-api`, and sample user is `lab`. Read the generated password from `.local/deploy/keycloak-user-password`. The local admin password is in `.local/deploy/keycloak-admin-password`. These files are private development secrets and must not be committed. Realm JSON import applies only when the local realm is first created; later changes need a Keycloak admin update or a fresh development realm.

An existing local realm retains its old HTTP redirect settings because Keycloak imports only on first creation. Update that client to the HTTPS values above in the Keycloak admin console. Caddy proxies the optional local Keycloak endpoint over HTTPS.

### Platform Admin bootstrap

Global Platform Admin grants are stored in the metadata database, keyed by the user's OIDC issuer and subject. After deploying the schema migration, bootstrap the first Platform Admin from inside the VM, replacing `KEYCLOAK_USER_ID` with the user's Keycloak `sub` claim (the user ID in the Keycloak admin console):

```sh
sudo -u storage-lab-api bash -c 'set -a; . /etc/storage-lab/api.env; export PYTHONPATH=/opt/storage-lab/backend/src; /opt/storage-lab/venv/bin/python -m storage_lab.platform_admin --issuer https://identity.eseidinger.de/realms/platform --subject KEYCLOAK_USER_ID'
```

The bootstrap command is idempotent. A Platform Admin can then add or remove other Platform Admins in the portal; the last one cannot be removed. After a grant, refresh the portal to load the new permission.

The old `storage-lab-portal-admin` Keycloak role is no longer part of the local realm import. If it already exists in a local or Platform realm, remove that existing role in Keycloak after confirming the metadata grant for each intended administrator; Ansible's import does not remove roles from existing realms.

To override the inventory's external issuer, set both `STORAGE_LAB_OIDC_ISSUER` and `STORAGE_LAB_OIDC_JWKS_URL` before running the application playbook. Set `STORAGE_LAB_OIDC_AUDIENCE` and `STORAGE_LAB_OIDC_CLIENT_ID` if those differ as well. Configure the portal client for code flow with PKCE, callback URL `https://localhost:8080/auth/callback`, and an access-token audience matching the API setting.

## Connect and verify

```sh
ssh -i .local/dev-vm/id_ed25519 -p 2222 \
  -o StrictHostKeyChecking=accept-new \
  -o UserKnownHostsFile=.local/dev-vm/known_hosts \
  lab@127.0.0.1
```

Caddy issues certificates from its local CA for `localhost`. Copy the CA root from the guest and trust it on the development host before using the portal or S3 gateway:

```sh
ssh -i .local/dev-vm/id_ed25519 -p 2222 lab@127.0.0.1 \
  'sudo podman cp storage-lab-caddy:/data/caddy/pki/authorities/local/root.crt /tmp/storage-lab-caddy-root.crt && sudo chmod 0644 /tmp/storage-lab-caddy-root.crt'
scp -i .local/dev-vm/id_ed25519 -P 2222 lab@127.0.0.1:/tmp/storage-lab-caddy-root.crt .local/dev-vm/caddy-root.crt
```

Import `.local/dev-vm/caddy-root.crt` into the host OS and browser trust stores. For command-line checks, use `curl --cacert .local/dev-vm/caddy-root.crt` or set `SSL_CERT_FILE` to this file for Python HTTP clients. Keep the CA data volume across deployments; replacing it changes the trusted root. The optional local Keycloak is also served through this CA on `https://localhost:8081`.

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
sudo -u storage-lab-worker bash -c 'set -a; source /etc/storage-lab/worker.env; export PYTHONPATH=/opt/storage-lab/backend/src; cd /opt/storage-lab/backend; /opt/storage-lab/venv/bin/python scripts/verify_documents.py'
sudo -u storage-lab-worker bash -c 'set -a; source /etc/storage-lab/worker.env; export PYTHONPATH=/opt/storage-lab/backend/src; cd /opt/storage-lab/backend; /opt/storage-lab/venv/bin/python scripts/verify_end_to_end.py'
```

The direct service scripts check PostgreSQL, S3, and CouchDB project isolation, CouchDB gateway filtering, idempotency, and revocation. The end-to-end script exercises API, worker, PostgreSQL migration/runtime access, S3 objects, CouchDB documents, cross-project denial, and cleanup with two temporary projects. If the optional local Keycloak is running, `SSL_CERT_FILE=.local/dev-vm/caddy-root.crt backend/.venv/bin/python backend/scripts/verify_oidc.py` verifies a real local token against the public API; it creates and removes a temporary password-grant client only for the test. The portal itself uses Authorization Code with PKCE. Check Caddy routes on the host:

```sh
curl --cacert .local/dev-vm/caddy-root.crt -i https://localhost:8080/api/health
curl --cacert .local/dev-vm/caddy-root.crt -i https://localhost:8080/auth/callback
curl --cacert .local/dev-vm/caddy-root.crt -i https://localhost:8080/couchdb/_all_dbs
curl --cacert .local/dev-vm/caddy-root.crt -i https://localhost:9000/rustfs/admin/v3/info
```

The API health and portal routes should return 200; the two administrative paths should return 403. Inspect `sudo systemctl status storage-lab-app storage-lab-caddy storage-lab-worker` and `sudo podman ps` in the guest if startup fails. API and UI use the single `storage-lab-app` image; the worker remains a host Python service. Caddy's certificate state is stored in the `storage-lab-caddy-data` Podman volume.

To stop the VM, send a termination signal to the PID in `.local/dev-vm/qemu.pid`. Run the first playbook again to restart it. Changes to cloud-init data after first boot require a fresh VM disk because the development VM uses a fixed cloud-init instance ID.

This inventory uses localhost certificates from Caddy's internal CA. For public deployment, set distinct `storage_lab_portal_host` and `storage_lab_s3_host` DNS names in a separate inventory, route ports 80 and 443 to Caddy, and set the Keycloak client's exact HTTPS redirect and web origins. Caddy then obtains and renews public ACME certificates. Configure public firewall rules, secret storage, backups, and restore separately.
