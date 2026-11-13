# Storage Lab architecture and API

**Status:** The PostgreSQL and RustFS delivery slice is implemented and runs in the Ansible-managed local VM. CouchDB, HugeGraph, Qdrant, Valkey, OpenSearch, ClickHouse, and NATS with JetStream remain planned. The [original German concept](../README_DE.md) defines the broader target; the [implementation plan](implementation-plan.md) tracks the remaining work.

## Components and boundaries

| Component | Current responsibility | Boundary |
| --- | --- | --- |
| React portal | OIDC login, projects, memberships, capability status, credentials, and S3 objects | Nginx at `localhost:8080` in development |
| FastAPI API | JWT validation, project authorization, metadata changes, object browser proxy | Nginx `/api/`; no service administration keys |
| Metadata PostgreSQL | Projects, memberships, capabilities, operations, credentials, audit events | Guest loopback port 5432; API and worker have separate database roles |
| Python worker | Leased operation processing and service reconciliation | Internal; holds application PostgreSQL and RustFS admin credentials |
| Application PostgreSQL | One database and non-login owner role per project | Guest port 5433; host loopback forwarding; TLS |
| RustFS | One private bucket and policy per project | Internal port 9000; public S3 data proxy on guest port 9002/host port 9000 |
| Local Keycloak | Development OIDC realm, portal client, and sample user | Host port 8081; replaceable with an external issuer |

The local VM uses HTTP for its portal, Keycloak, and S3 gateway, and exposes forwarded ports only on the host loopback interface. Production deployment still requires DNS, trusted TLS certificates, HTTPS/WSS routing, secret management, backup and restore procedures, monitoring, and a separate inventory. Administrative S3 routes are blocked by Nginx; RustFS itself binds to guest loopback. The metadata database is not forwarded.

## Identity and project authorization

The portal uses OIDC Authorization Code with PKCE. The API accepts RS256 access tokens only after verifying the signature against JWKS and checking issuer, audience, expiry, and required claims. It maps `(iss, sub)` to a local membership. A project creator becomes its first administrator. Administrators can manage members, capabilities, credentials, and objects; viewers can read project information and download objects. The API checks membership for project and operation routes and returns 404 for unauthorized project access. The final administrator cannot be demoted.

A portal identity and a workload credential have different purposes. Workload credentials authenticate directly to PostgreSQL or S3 and carry no API membership. Credential secrets are returned only from the issuance request. The encrypted secret stays in an operation payload until the worker finishes; ordinary API responses and audit events expose no secret. The portal keeps the one-time value in component state while the dialog is open.

## Resource model and lifecycle

A project can activate each implemented capability once. Resource names derive from the immutable project ID, not the display name. The API commits desired capability state and an operation in one metadata transaction. It reuses the existing operation for a repeated activation while the capability is pending or ready. The worker claims a pending job with `FOR UPDATE SKIP LOCKED` and a five-minute lease, then reconciles the service resource. Failed jobs expose a redacted error and may be retried up to five attempts. The adapters inspect existing resources, so a retry after partial provisioning does not create a second database or bucket.

The current worker handles short operations and has no lease heartbeat. A service call lasting longer than five minutes could be claimed by another worker; longer operations need lease renewal before more workers or capabilities are added. Credential rotation is done by issuing a replacement and revoking the old credential. Confirmed capability deletion revokes credentials and removes its resource and data. There is no project deletion endpoint yet.

### PostgreSQL

The worker creates a project database and a non-login owner role, revokes `PUBLIC` database access, and revokes `PUBLIC` schema access. A `runtime` credential receives `CONNECT`, schema `USAGE`, and data privileges on existing and future owner-created tables and sequences. A `migration` credential receives membership in the owner role. A migration session must execute `SET ROLE <migration_role>` before DDL so new objects are owned by the project owner and runtime default privileges apply. Neither credential receives cluster administration rights. The live verification checks runtime DML, denied runtime DDL, denied cross-project connection, and TLS hostname verification.

Clients should connect to `localhost:5433` in the local VM with `sslmode=verify-full` and the VM's `/etc/ssl/certs/storage-lab-pg.crt` as `sslrootcert`. A different deployment must use its own DNS name and certificate. The worker's provisioning check requires TLS; the live test checks the certificate and hostname.

### RustFS S3 and object browser

The worker creates a private bucket and a bucket-scoped policy. Each workload gets its own RustFS user and key pair; a separate encrypted project browser identity lets the API list, upload, download, and delete objects after checking membership. The object list uses pagination. Browser transfers go through the API, so no S3 CORS or presigned URL flow is required for the current portal. The live test checks that one project's key cannot access another project's bucket and that the public gateway rejects an administrative route.

## API surface

The Nginx prefix is `/api`; the FastAPI routes below are relative to that prefix. The generated OpenAPI schema is available at `/api/openapi.json` in development.

| Method and route | Purpose |
| --- | --- |
| `GET /health` | Process health |
| `POST /projects`, `GET /projects`, `GET /projects/{id}` | Create and read projects |
| `GET /projects/{id}/members`, `POST /projects/{id}/members` | Read and add/update members |
| `GET /projects/{id}/capabilities`, `GET /projects/{id}/capabilities/{kind}` | Read capability status and connection details |
| `PUT /projects/{id}/capabilities/{kind}` | Start or reuse provisioning |
| `DELETE /projects/{id}/capabilities/{kind}` | Start deletion with `confirm_name` in the JSON body |
| `GET /operations/{id}`, `POST /operations/{id}/retry` | Observe and retry an operation |
| `GET /projects/{id}/capabilities/{kind}/credentials` | List credential metadata for administrators |
| `POST /projects/{id}/capabilities/{kind}/credentials` | Issue a one-time secret and start provisioning |
| `DELETE /projects/{id}/capabilities/{kind}/credentials/{credential_id}` | Revoke a credential |
| `GET /projects/{id}/objects`, `POST /projects/{id}/objects` | List and upload S3 objects |
| `GET /projects/{id}/objects/download?key=...`, `DELETE /projects/{id}/objects?key=...` | Download and delete S3 objects |

Asynchronous mutations return an operation ID; the portal polls until success or failure. The capability kinds currently accepted are `postgresql` and `object-storage`.

## Operations and recovery

Alembic manages metadata schema revisions. Ansible deploys pinned Python dependencies, builds the portal, applies migrations, installs systemd units, and configures Nginx and the data services. Re-running the playbook preserves the VM disk and service volumes. The [VM guide](development-vm.md) gives the verification procedure.

Backup and restore automation is not implemented. Before any non-development deployment, define separate backup targets and restore tests for metadata PostgreSQL, application PostgreSQL, RustFS data, and encryption keys. Restore must reconcile metadata with service resources before worker jobs resume. The current local TLS certificate is self-signed and expires after one year; production certificate renewal is also outstanding.

## Planned capabilities

| Capability | Proposed project resource | Required isolation check |
| --- | --- | --- |
| `documents` | CouchDB database | Database `_security` membership |
| `graph` | HugeGraph graph | Graph-scoped roles and API access |
| `vectors` | Qdrant collection | Collection-restricted token |
| `key-value` | Valkey key namespace | Prefix and command ACL |
| `search` | OpenSearch index or prefix | Index-scoped role and dashboard isolation |
| `analytics` | ClickHouse database | Database-scoped role and query limits |
| `events` | NATS account, streams, consumers | Account, subject, and JetStream isolation |

Each adapter must demonstrate provisioning, project isolation, credential lifecycle, deletion, retry, and restore behavior before being exposed in the portal.
