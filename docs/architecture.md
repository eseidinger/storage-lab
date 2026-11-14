# Storage Lab architecture and API

**Status:** PostgreSQL, RustFS, CouchDB, Valkey, ClickHouse, Qdrant, OpenSearch, HugeGraph, and NATS with JetStream have adapters and Compose services. The development inventory uses the Platform Keycloak realm; no local Keycloak is deployed. The [original German concept](../README_DE.md) defines the broader target; the [implementation plan](implementation-plan.md) tracks the remaining work.

## Components and boundaries

| Component | Current responsibility | Boundary |
| --- | --- | --- |
| React portal | OIDC login, projects, memberships, capability status, credentials, S3 objects, and JSON documents | Bundled in the API image; Caddy at `https://localhost:8080` |
| FastAPI API | JWT validation, project authorization, metadata changes, project-scoped object and document views | Caddy `/api/` to the combined app container; no service administration keys |
| Metadata PostgreSQL | Projects, memberships, platform administrators, capabilities, operations, credentials, audit events | Docker internal network only; API and worker have separate database roles |
| Python worker | Leased operation processing and service reconciliation | Dedicated container from the shared app image; holds application PostgreSQL, RustFS, and CouchDB admin credentials |
| Application PostgreSQL | One database and non-login owner role per project | Docker container, guest port 5433, host loopback forwarding, TLS |
| RustFS | One private bucket and policy per project | Docker internal port 9000; Caddy HTTPS gateway on guest port 9443/host port 9000 |
| CouchDB | One protected JSON database per project | Docker internal port 5984; Caddy exposes project database paths under `/couchdb/` |
| Valkey | Project key prefix and per-workload ACL user | Docker internal port 6379 and TLS on guest/host port 6380 |
| ClickHouse | Project database and role with query limits | Docker internal port 8123; Caddy HTTPS gateway on guest port 9444/host port 9001 |
| Qdrant | Project collection and scoped JWT | Docker internal port 6333; Caddy HTTPS gateway on guest port 9445/host port 9003 |
| OpenSearch | Project index and role; separate Dashboards tenant | Docker internal port 9200; local Caddy HTTPS gateways on guest ports 9446/9447 |
| HugeGraph | Project graph and graph-scoped group/target | Docker internal port 8080; local Caddy HTTPS gateway on guest port 9448 |
| NATS | Project account and JetStream stream | Native TLS on guest and host port 4222 |
| Platform Keycloak | OIDC realm and portal client used by the development inventory | `https://identity.eseidinger.de/realms/platform` |

Caddy terminates HTTPS for the portal, S3 gateway, and CouchDB data path using a persistent local CA in the development VM. The Platform Keycloak endpoint also uses HTTPS. Forwarded ports bind to the host loopback interface. A public deployment needs DNS, public certificate issuance, secret management, backup and restore procedures, monitoring, and a separate inventory. Administrative S3 routes and all global CouchDB routes are blocked by Caddy; both services are reachable only on the internal Docker network. The metadata database is not forwarded.

## Identity and project authorization

The portal uses OIDC Authorization Code with PKCE. The API accepts RS256 access tokens only after verifying the signature against JWKS and checking issuer, audience, expiry, and required claims. It maps `(iss, sub)` to local authorization records. A project creator becomes its first administrator. Project administrators can manage members, capabilities, credentials, and objects; viewers can read project information and download objects. The metadata `platform_admins` table grants global `platform-admin` access by `(iss, sub)`: these users can see and administer every project without project membership, and manage other platform administrators. Grants and revocations are recorded in `platform_admin_events`. Keycloak provides authentication; Storage Lab stores the permissions. The API checks membership or the metadata Platform Admin grant for project and operation routes and returns 404 for unauthorized project access. The final project administrator and the final Platform Admin cannot be removed.

A portal identity and a workload credential have different purposes. Workload credentials authenticate directly to PostgreSQL, S3, or CouchDB and carry no API membership. Credential secrets are returned only from the issuance request. The encrypted secret stays in an operation payload until the worker finishes; ordinary API responses and audit events expose no secret. The portal keeps the one-time value in component state while the dialog is open.

## Resource model and lifecycle

A project can activate each implemented capability once. Resource names derive from the immutable project ID, not the display name. The API commits desired capability state and an operation in one metadata transaction. It reuses the existing operation for a repeated activation while the capability is pending or ready. The worker claims a pending job with `FOR UPDATE SKIP LOCKED` and a five-minute lease, then reconciles the service resource. Failed jobs expose a redacted error and may be retried up to five attempts. The adapters inspect existing resources, so a retry after partial provisioning does not create duplicate databases or buckets.

The current worker handles short operations and has no lease heartbeat. A service call lasting longer than five minutes could be claimed by another worker; longer operations need lease renewal before more workers or capabilities are added. Credential rotation is done by issuing a replacement and revoking the old credential. Confirmed capability deletion revokes credentials and removes its resource and data. There is no project deletion endpoint yet.

### PostgreSQL

The worker creates a project database and a non-login owner role, revokes `PUBLIC` database access, and revokes `PUBLIC` schema access. A `runtime` credential receives `CONNECT`, schema `USAGE`, and data privileges on existing and future owner-created tables and sequences. A `migration` credential receives membership in the owner role. A migration session must execute `SET ROLE <migration_role>` before DDL so new objects are owned by the project owner and runtime default privileges apply. Neither credential receives cluster administration rights. The live verification checks runtime DML, denied runtime DDL, denied cross-project connection, and required TLS on internal connections.

Clients should connect to `localhost:5433` in the local VM with `sslmode=verify-full` and the VM's `/opt/storage-lab/certs/postgres.crt` as `sslrootcert`. A different deployment must use its own DNS name and certificate. The worker's provisioning check requires TLS; the live test checks the certificate and hostname.

### RustFS S3 and object browser

The worker creates a private bucket and a bucket-scoped policy. Each workload gets its own RustFS user and key pair; a separate encrypted project browser identity lets the API list, upload, download, and delete objects after checking membership. The object list uses pagination. Browser transfers go through the API, so no S3 CORS or presigned URL flow is required for the current portal. The live test checks that one project's key cannot access another project's bucket and that the public gateway rejects an administrative route.

### CouchDB documents

The worker creates a database named from the immutable project ID, then sets `/{db}/_security` with named members and no public roles. A separate encrypted browser identity lets the API list and edit documents after checking project membership. Each workload credential creates a CouchDB user and adds its name to the database members. Revocation removes the member and user; the final member is retained in the security object until database deletion to avoid briefly exposing an open database. The portal lists document IDs with pagination and edits JSON using CouchDB revisions. The public Caddy gateway forwards only `/couchdb/sl_<project-id>/...` paths; global routes and database administration routes are blocked, while `/_all_docs` remains available for document listing. The live test verifies anonymous denial, cross-project denial, revocation, gateway filtering, and reprovisioning. See [CouchDB database security](https://docs.couchdb.org/en/stable/api/database/security.html).

## API surface

The Caddy prefix is `/api`; the FastAPI routes below are relative to that prefix. The generated OpenAPI schema is available at `/api/openapi.json` in development.

| Method and route | Purpose |
| --- | --- |
| `GET /health` | Process health |
| `GET /me` | Return whether the signed-in user is a Platform Admin |
| `GET /platform-admins`, `POST /platform-admins`, `DELETE /platform-admins` | List, grant, and revoke global Platform Admin access; only Platform Admins may use these routes |
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
| `GET /projects/{id}/documents?skip=...`, `GET /projects/{id}/documents/{doc_id}` | List and read CouchDB documents |
| `PUT /projects/{id}/documents/{doc_id}`, `DELETE /projects/{id}/documents/{doc_id}?rev=...` | Create, update, and delete JSON documents |

Asynchronous mutations return an operation ID; the portal polls until success or failure. The capability kinds currently accepted are `postgresql`, `object-storage`, `documents`, `key-value`, `analytics`, `vectors`, `search`, `graph`, and `events`.

## Operations and recovery

Alembic manages metadata schema revisions. Ansible builds one image containing the API and portal, applies migrations in a temporary container, and starts all services with Docker Compose. Re-running the playbook preserves the VM disk and service volumes. The [VM guide](development-vm.md) gives the verification procedure.

Backup and restore automation is not implemented. Before any non-development deployment, define separate backup targets and restore tests for metadata PostgreSQL, application PostgreSQL, RustFS and CouchDB data, and encryption keys. Restore must reconcile metadata with service resources before worker jobs resume. The local Caddy CA is trusted manually on development hosts. Caddy handles ACME certificates when configured for public DNS names on ports 80 and 443.

### Valkey key-value

The worker grants each workload an ACL user limited to keys beginning with `sl_<project-id>:` and an explicit list of string, expiry, and deletion commands. `ACL SETUSER reset` removes any older grant before applying the current rules; `ACL SAVE` persists issuance and revocation in the Valkey data volume. Deleting a capability scans and unlinks only that project's keys. The default user is disabled. Clients connect to `localhost:6380` using TLS and the server certificate at `/opt/storage-lab/certs/postgres.crt`. The worker uses the internal Docker port and an administrator password. A live cross-project and TLS check is still required before relying on it outside development.

### ClickHouse analytics

The worker creates one database and one role per project. The role grants table access only inside that database and sets a 30-second execution limit, a 1 GiB memory limit, a row-read limit, and four threads. Each workload receives a separate password user with that role as its default. Revocation drops the user; deletion drops the database and role. HTTP clients connect through the Caddy gateway at `https://localhost:9001` with Basic authentication and select their database in the query. The adapter has unit coverage for scoped grants and identifier validation; live privilege and TLS checks remain necessary.

### Qdrant vectors

The worker creates one 1536-dimensional cosine collection per project. It signs a collection-scoped read/write JWT with the Qdrant admin key and stores a matching point in an internal credential registry. The JWT's `value_exists` claim requires that point; revocation deletes it. The registry is outside the JWT's collection access. Because the worker alone holds the signing key, the API returns no secret from the initial issuance request. After the operation succeeds, a project administrator claims the token once through the portal or API; it is encrypted in metadata until claimed. Clients connect to `https://localhost:9003` and send the token in the `api-key` header. Collection schema is currently fixed at 1536 dimensions; add a project-specific dimension setting before using other embedding models. A live cross-project and revocation check remains necessary.

### OpenSearch search

The worker creates a project index, Dashboard tenant, and role restricted to that index and the `sl_<project-id>-*` pattern. A workload receives an internal user mapped to the project role and the built-in Dashboard login role. Revocation removes the user; deletion removes matching project indices, role, and tenant. The local development gateway exposes the REST API at `https://localhost:9005` and Dashboards at `https://localhost:9006`; Caddy blocks security administration paths. OpenSearch currently uses its demo security configuration and bundled certificates, and Dashboards uses the bundled service user. Keep these gateways loopback-only; replace the demo security setup before any public deployment. Live tenant and index isolation checks are still needed.

### HugeGraph graph

The worker creates a RocksDB-backed graph per project with authentication enabled, a graph-specific target, and a group granted read, write, delete, and execute permissions on that target. Each workload user belongs only to that group. Revocation deletes its association and user; capability deletion removes grants, target, group, and graph. The local Caddy gateway at `https://localhost:9007` allows only paths beneath `/graphspaces/DEFAULT/graphs/sl_<project-id>` and denies HugeGraph administration endpoints. HugeGraph uses HTTP Basic authentication behind that TLS gateway. A live two-project access check remains necessary.

### NATS events

The worker gives each project a separate NATS account and a file-backed JetStream stream for subjects beginning with `sl_<project-id>.`. It renders bcrypt password users in a persistent configuration file and asks the NATS system account to reload it after issuance or revocation. A deployment initialization job creates the initial configuration before the server starts. The native TLS endpoint is `tls://localhost:4222`; clients must trust the VM certificate. Deleting the capability removes its stream and account. A live two-account isolation and reload check is still needed.
