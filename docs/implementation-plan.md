# Storage Lab implementation plan

**Planning basis:** The [project documentation](architecture.md) and [German source concept](../README_DE.md). The repository currently has development infrastructure automation but no application code. This plan defines proposed work and acceptance criteria; it does not imply that any phase is complete.

## Delivery principle

Build one complete, isolated flow for PostgreSQL and S3 before adding more services. Keep the API's desired state and operation state in metadata PostgreSQL, with a separate worker that reconciles actual service state. A capability is ready only when provisioning, authorization, credential lifecycle, deletion, and recovery work for two different projects.

## Phase 1 — Foundation and contracts

**Work**

- Define project roles, capability states, operation states, error categories, and stable resource naming rules.
- Specify API request and response schemas, including how a repeated `PUT` reuses an operation and how deletion is confirmed.
- Use Ansible for the local VM and subsequent application deployment. The development VM is specified with 16 vCPUs and 32 GiB RAM; define separate inventories for later environments.
- Set up the application repository structure, local single-host service deployment, configuration, secrets handling, and versioned metadata migrations.
- Provision separate metadata and application PostgreSQL instances and establish private worker administration access.
- Configure the portal OIDC client, API audience, DNS names, TLS, and public versus private routes.

**Acceptance**

- The API rejects invalid signatures, issuers, audiences, and expired tokens.
- A valid user without project membership cannot read or change that project, including its operations.
- The metadata database and service administration endpoints are not reachable through public data routes.
- API and worker use separate least-privilege metadata roles.
- The [development VM](development-vm.md) can be recreated from Ansible without committing its disk or SSH key.

## Phase 2 — Project and operation workflow

**Work**

- Implement the React project list and project detail flow, project creation, membership checks, and capability status views.
- Implement the Python API with transactional writes of desired capability state and provisioning jobs.
- Implement leased job claiming, retries, observable failure reasons, and reconciliation after worker interruption.
- Add audit events that record actors and resource references without secret values.

**Acceptance**

- Repeating an activation request for the same target state does not schedule duplicate resources.
- A failed capability shows its own error and retry path without changing another capability's status.
- A worker restart can resume a partially completed operation from observed service state.

## Phase 3 — PostgreSQL adapter

**Work**

- Create a project database and non-login owner role on the application instance.
- Create distinct migration and runtime login roles; revoke default access and grant only required database, schema, and object privileges.
- Issue, rotate, and revoke workload passwords; expose only non-secret connection details in ordinary API responses.
- Verify TLS connections with hostname checking and project isolation through the public endpoint.
- Implement deletion and reconciliation for partial database or role creation.

**Acceptance**

- Projects A and B can each connect to their own database and perform permitted operations.
- Each project's roles are denied access to the other project's database and to administration privileges.
- After interruption between database creation and grants, a retry leaves exactly one usable database with the intended owner and privileges.

## Phase 4 — RustFS S3 adapter and object view

**Work**

- Validate the selected RustFS version's administrative support for bucket creation, policies, credential issuance, and revocation.
- Create a private bucket and project-scoped policy; support separate credentials per workload.
- Display connection details and build a project object list with upload and download.
- If direct browser transfers are used, issue short-lived presigned URLs after authorization and configure only the necessary CORS origin.
- Implement credential rotation, revocation, bucket deletion, and recovery after partial creation.

**Acceptance**

- Projects A and B can upload and download their own objects but cannot list or read each other's buckets.
- A revoked credential no longer grants access.
- Browser actions and direct S3 requests enforce the same project boundary.

## Phase 5 — Recovery and first release gate

**Work**

- Exercise backup and restore separately for metadata PostgreSQL, application PostgreSQL, and RustFS data.
- Reconcile restored metadata with actual databases, buckets, roles, and credentials before worker jobs resume.
- Document operator procedures for failed jobs, credential rotation, and confirmed deletion.
- Verify public endpoint exposure and confirm that metadata and administrative access remain private.

**First release gate**

- Two projects complete portal sign-in, project creation, PostgreSQL provisioning, S3 provisioning, credential issuance, and data access.
- Cross-project access fails through the API, job-status endpoint, PostgreSQL, S3, and browser views.
- Wrong-audience tokens fail, and users without lab membership cannot enter another project.
- Interrupted jobs resume without duplicate resources; a backup can be restored and reconciled.

## Phase 6 — Additional capabilities

Add adapters one at a time: CouchDB, HugeGraph, Qdrant, Valkey, OpenSearch, ClickHouse, and NATS with JetStream. For each adapter, first verify the selected service version's administrative and access-control APIs. Then implement provisioning, project-scoped credentials, access checks, rotation, revocation, deletion, retry, and restore reconciliation. Add a portal view or native dashboard only after direct API access and browser access enforce the same project boundary. JetStream needs an explicit test with separate NATS accounts.

## Decisions to settle during Phase 1

| Decision | Why it matters |
| --- | --- |
| Exact project role model and invitation flow | Determines who can create projects, enable capabilities, view data, and manage credentials |
| Secret delivery and storage mechanism | Determines how one-time credential values reach workloads and how rotation is audited |
| Service versions and deployment layout | Determines which adapter APIs and isolation features can be relied upon |
| Per-service quotas and resource limits | Prevents one project from exhausting the shared host where the service supports limits |
| Backup targets, retention, and restore objectives | Determines whether recovery meets the lab's operational needs |
| Deletion retention and confirmation semantics | Prevents accidental loss and defines the worker's cleanup behavior |
