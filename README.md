# Storage Lab

Storage Lab is a single-host platform for project-scoped data services. Members sign in through OIDC, create projects, enable services, and manage workload credentials in a React portal. A Python API stores desired state and authorizes requests; a separate worker provisions resources.

**Implemented now:** project membership and roles, asynchronous operations, PostgreSQL databases, private RustFS S3 buckets, workload credential issuance and revocation, an S3 object browser, and an Ansible-deployed local development VM. The other seven services in the [original concept](README_DE.md) remain planned. The current deployment is a local development environment with loopback host forwarding and HTTP; it is not a production deployment.

## Technology

- **API and worker:** Python, FastAPI, Pydantic, SQLAlchemy, Alembic, psycopg, boto3, and PyJWT.
- **Portal:** React, TypeScript, Mantine, Vite, React Router, TanStack Query, and `oidc-client-ts`.
- **Deployment:** Ansible, systemd, Nginx, two separate PostgreSQL clusters, RustFS, and a local Keycloak realm for development.

The [technology decisions](docs/technology-decisions.md) explain each library's role.

## Run the local environment

The VM needs 16 vCPUs, 32 GiB RAM, an 80 GiB virtual disk, QEMU, Ansible, and access to the Ubuntu 24.04 cloud image on its first run. From the repository root:

```sh
ansible-playbook ansible/playbooks/dev-vm.yml
ansible-playbook -i ansible/inventory/dev.yml ansible/playbooks/app.yml
```

Open `http://localhost:8080`, sign in as `lab`, and read the generated password from `.local/deploy/keycloak-user-password`. Development secrets and VM state remain under the ignored `.local/` directory. The API is exposed at `http://localhost:8080/api`; PostgreSQL and the public S3 gateway are forwarded to `localhost:5433` and `localhost:9000`. Keycloak is at `http://localhost:8081`. The metadata PostgreSQL cluster and RustFS administrative API are not forwarded. See the [VM guide](docs/development-vm.md) for SSH access, certificate setup, and verification commands.

Set `STORAGE_LAB_OIDC_ISSUER`, `STORAGE_LAB_OIDC_JWKS_URL`, `STORAGE_LAB_OIDC_AUDIENCE`, and `STORAGE_LAB_OIDC_CLIENT_ID` before running the application playbook to use an external Keycloak realm instead of the local development realm. Configure that realm's portal client for Authorization Code with PKCE, redirect URI `http://localhost:8080/auth/callback`, and an access-token audience matching the API setting.

## Current project workflow

1. Sign in and create a project. The creator is its first administrator.
2. Enable PostgreSQL or object storage. The API commits a capability record and operation; the worker reconciles the resource and reports status.
3. Issue a one-time workload credential. PostgreSQL offers `runtime` access for data operations and `migration` access for schema changes. Migration sessions must run `SET ROLE <migration_role>` before creating objects so runtime grants apply to future tables. S3 credentials are restricted to the project's bucket.
4. Use the portal to list, upload, download, and delete S3 objects. Project viewers can read; administrators can change resources and credentials.
5. Revoke credentials or delete a capability after confirming the project name. Deletion removes its data.

PostgreSQL clients should use TLS with hostname verification and trust the VM's `/etc/ssl/certs/storage-lab-pg.crt`. The development S3 endpoint uses HTTP on the local host only. Credentials are shown once when issued; operation and audit responses exclude secret values.

## Development checks

```sh
cd backend && .venv/bin/pytest -q
cd frontend && npm run build
```

The live verification scripts under `backend/scripts/` exercise service isolation, the API and worker lifecycle, and local OIDC. They run against the provisioned VM; commands and expected results are in the [VM guide](docs/development-vm.md).

## Documentation

- [Architecture and API](docs/architecture.md)
- [Implementation status and remaining plan](docs/implementation-plan.md)
- [Technology decisions](docs/technology-decisions.md)
- [Local development VM](docs/development-vm.md)
- [Original German concept](README_DE.md)
