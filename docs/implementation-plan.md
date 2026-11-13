# Storage Lab implementation plan

The [architecture](architecture.md) describes the current three-capability system. This plan separates work already implemented from release gates that remain open. The broader scope comes from the [original German concept](../README_DE.md).

## Current implementation

| Area | Status and evidence |
| --- | --- |
| Foundation | Python FastAPI API and worker, React/TypeScript/Mantine portal, SQLAlchemy models, Alembic migrations, pinned Python and npm dependencies |
| Local deployment | Ansible creates a 16-vCPU, 32-GiB Ubuntu VM and deploys two PostgreSQL clusters, RustFS, CouchDB, API, worker, portal, and Nginx; the Platform Keycloak realm is configured, with local Keycloak optional |
| Identity and projects | OIDC token verification, local project memberships, administrator/viewer roles, project and operation authorization, audit records |
| Provisioning | Transactional operation creation, worker leasing, idempotent PostgreSQL/S3/CouchDB reconciliation, error reporting and retry |
| PostgreSQL | Project database, non-login owner, separate migration/runtime credentials, TLS, revocation, deletion, cross-project access test |
| Object storage | Private RustFS bucket and policy, per-workload keys, revocation, deletion, API-backed object browser, cross-project access test |
| Documents | Private CouchDB database, per-project members, separate workload users, revocation, deletion, paginated JSON document view, cross-project access test |
| Verification | Backend tests, frontend production build, live two-project API/worker/service verification, and a real local Keycloak token accepted by the API |

This is a working **local development slice**, not a completed production release. Browser login is configured with the Platform Keycloak realm. A full automated browser journey and verification of the Platform realm's issued access-token audience are still outstanding; the earlier API token check used the optional local realm. The project's six additional service adapters are not implemented.

## Next gate — first release quality

1. Add an automated browser journey for sign-in, project creation, capability status, credential issuance, object operations, and document operations. Repeat it with two identities and verify authorization failures for cross-project API and browser access.
2. Add worker lease renewal or limit concurrency to one worker and enforce a timeout shorter than the lease. Exercise interruption during each adapter step and verify recovery from observed PostgreSQL, RustFS, and CouchDB state.
3. Define quotas, upload size limits, S3 object pagination UX, and operation metrics. Add endpoint health checks to the deployment playbook.
4. Add backup and restore automation for metadata PostgreSQL, application PostgreSQL, RustFS, CouchDB, and encryption keys. Restore a test backup and reconcile before restarting the worker.
5. Prepare a production inventory with DNS, trusted TLS, certificate renewal, secret storage, monitoring, firewall rules, and exposure tests. Confirm that the Platform client includes `storage-lab-api` in access-token audiences.
6. Define project deletion and retention policy. Make destructive operations follow the approved retention period and verify credential revocation before deletion.

**Release acceptance:** Two projects complete sign-in, PostgreSQL, S3, and CouchDB provisioning, credential issuance, data access, revocation, and confirmed deletion. Each project is denied access to the other's API state, PostgreSQL database, S3 bucket, CouchDB database, and browser views. Wrong-issuer, wrong-audience, expired, and unsigned tokens fail. An interrupted job resumes without duplicate resources. Backups restore successfully, and only intended data endpoints are public.

## Later capabilities

Add one service adapter at a time: HugeGraph, Qdrant, Valkey, OpenSearch, ClickHouse, and NATS with JetStream. For each selected service version, verify its administrative and access-control APIs first. Then implement resource creation, per-project authorization, workload credentials, rotation, revocation, deletion, retry, restore reconciliation, and a project-safe portal view. JetStream requires a dedicated test with separate NATS accounts.

## Decisions still needed

| Decision | Impact |
| --- | --- |
| Platform access-token audience verification | Confirms that browser tokens contain `storage-lab-api` |
| Backup targets, retention, and recovery objectives | Determines restore procedure and release gate |
| Per-service quotas and host capacity | Prevents a project from exhausting the shared host |
| Project deletion retention | Defines when data is irreversibly removed |
| Production DNS, TLS, and secret store | Defines the public endpoint and operator boundary |
