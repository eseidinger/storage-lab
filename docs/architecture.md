# Storage Lab project documentation

**Document status:** Proposed design, based on the existing [German concept](../README_DE.md). This repository currently contains documentation and development infrastructure automation, but no application code. Component names, endpoints, and service integrations below describe intended behavior, not deployed functionality.

The development environment is provisioned through [Ansible on a local VM](development-vm.md). Application deployment should also use Ansible as the project moves from this proposal to runnable services.

The API and worker will be implemented in Python; the portal will use React, TypeScript, and Mantine. The supporting libraries and their responsibilities are recorded in [technology decisions](technology-decisions.md).

## Purpose and scope

Storage Lab is a standalone, single-host lab that would provide project-scoped databases, object storage, and specialized data services. The Developer Platform supplies Keycloak as the identity provider; the lab owns project membership, resource lifecycle, workload credentials, and data-service access. Applications and external clients connect to public lab data endpoints. Operators use private administrative endpoints.

The first delivery slice comprises the React portal, Python API, provisioning worker, an internal metadata PostgreSQL instance, an application PostgreSQL instance, and RustFS. CouchDB, Apache HugeGraph, Qdrant, Valkey, OpenSearch, ClickHouse, and NATS with JetStream are planned extensions.

## Components and ownership

| Component | Responsibility | Access boundary |
| --- | --- | --- |
| React portal (TypeScript and Mantine) | Project management, capability selection, status, connection details, credential controls, and project data views | Public HTTPS; users authenticate through Keycloak |
| Python API (FastAPI) | Validate tokens and project roles; store projects, desired state, jobs, and audit events; return project-scoped information | Public HTTPS for authorized portal requests |
| Metadata PostgreSQL | Projects, memberships, capability state, resource references, jobs, and audit records | Internal only; separate API, worker, and operator roles |
| Python provisioning worker | Reserve jobs, reconcile actual resources with desired state, configure access, and verify results | Internal metadata and private service administration access |
| Application PostgreSQL | Host project databases | Public TLS data port for permitted project roles; private administration access |
| RustFS and future stores | Host project resources behind service-specific authorization | Public data endpoints; private administration endpoints |

Both PostgreSQL instances would run on the lab host but serve different trust and data boundaries. Versioned database migrations would manage the metadata schema. The job queue can reside in metadata PostgreSQL, allowing the worker to provision JetStream without depending on JetStream itself.

## Identity and authorization

The portal would use OIDC Authorization Code with PKCE against the Developer Platform's Keycloak. It needs a dedicated portal client and the API needs its own audience. The API must validate the access token's signature, issuer, audience, and validity using OIDC metadata and JWKS. It maps `(iss, sub)` to a lab identity and checks local project membership and role on every project-scoped request, including job status and dashboard access.

Project membership and workload access are separate. A person's portal role does not grant a workload direct data access, and a workload credential does not grant portal access. Project administrators can manage capabilities and credentials; any finer role model should be defined before API implementation.

Public data endpoints require DNS names, TLS with hostname verification, and authorization enforced by each service. HTTPS and WSS services may share a reverse proxy. PostgreSQL and Valkey need their own TLS data ports; NATS may also offer native TLS. The metadata database, management UIs, cluster ports, and service administration endpoints stay on an internal network or behind a separate administrative access path. If a public HTTP proxy is shared, it must block management routes that can be separated from data routes.

## Capability and resource model

The first API model permits at most one activation of each capability per project. Resources use names derived from the immutable internal project ID. Service-level limits should be configured where a service can enforce them for an individual project.

| Capability | Planned project resource | Planned access boundary |
| --- | --- | --- |
| `postgresql` | Application database | Dedicated login roles with rights only to that database and intended schemas |
| `object-storage` | Private RustFS S3 bucket | Project identity and policy restricted to that bucket |
| `documents` | CouchDB database | Membership managed through `/{db}/_security` |
| `graph` | HugeGraph graph | Project group restricted to its graph and required operations |
| `vectors` | Qdrant collection | Time-limited token restricted to the collection |
| `key-value` | Valkey project key namespace | ACL for allowed key prefixes and commands; database-level ACLs require version validation |
| `search` | OpenSearch index or index prefix | Index role and, if needed, a Dashboards tenant for saved views |
| `analytics` | ClickHouse database | Role restricted to project tables and query limits |
| `events` | NATS account with streams and consumers | Separate users with scoped subject and JetStream rights |

These access controls are adapter requirements, not claims that every service integration is already proven. Each adapter needs a version-specific feasibility check and an isolation test before release.

### Application PostgreSQL

The worker would use a dedicated administrative role on the application instance to create a database and a separate, non-login owner role for each project. It would revoke default `CONNECT` access from `PUBLIC` and grant access only to intended project roles before exposing the connection details. A migration role gets the necessary DDL rights. A runtime role gets only the schema and object permissions the application needs. Default privileges for future objects must be set for the role that actually creates them. Application roles must not have superuser, role-management, or database-management rights.

The portal would display host, port, database name, and username. Clients must use TLS with hostname verification, for example libpq's `sslmode=verify-full`. Password issuance and rotation are separate actions. Since `CREATE DATABASE` cannot run inside a transaction block, the worker must inspect the actual database, owner, and grants when resuming an interrupted job. See the PostgreSQL documentation for [database creation](https://www.postgresql.org/docs/current/sql-createdatabase.html) and [privileges](https://www.postgresql.org/docs/current/ddl-priv.html).

### S3 through RustFS

The worker would create a private bucket and project identity in the lab's RustFS instance. It may issue a separate access pair per application. Bucket-list operations must be scoped to the project bucket; object operations must be scoped to the objects inside it. The portal would display the S3 endpoint, bucket, region, and addressing guidance where needed.

The project object view should list objects and support upload and download. For direct browser transfers, the backend may issue short-lived presigned URLs after checking project membership; the S3 endpoint would then need CORS for the portal origin. Before exposing the capability, the adapter must validate bucket creation, policy attachment, credential issuance, and revocation against the selected RustFS version. See [RustFS IAM documentation](https://docs.rustfs.com/en/security-compliance/iam).

## Provisioning lifecycle

1. The API checks authorization and input, then commits the desired capability state and its job in one metadata transaction. A repeated request for the same target state must reuse the operation rather than create another resource.
2. The worker claims a job with a finite lease, derives stable resource names, and inspects existing resources before changing them.
3. The adapter creates or reconciles the resource and its project permissions, then verifies access with a project-scoped identity.
4. On success, the worker stores the resource reference and endpoint information. On failure, it stores a useful error and allows a controlled retry without affecting other capabilities.
5. Credential issuance, rotation, and revocation are explicit project-administrator operations. Deletion requires a confirmed request and must account for credentials and dependent resources.

Job leasing, retry rules, and reconciliation are needed because a worker can stop between a service operation and a metadata update. Actual service state must be checked on restart. The portal reads each capability's state separately so one failed adapter does not hide successful ones.

### Proposed API surface

| Operation | Intended behavior |
| --- | --- |
| `POST /projects` | Create a project |
| `GET /projects/{project_id}` | Read project details and capability status |
| `PUT /projects/{project_id}/capabilities/{kind}` | Enable a capability or reuse the operation for the same desired state |
| `GET /projects/{project_id}/capabilities/{kind}` | Read status, endpoint, and resource reference |
| `POST /projects/{project_id}/capabilities/{kind}/credentials` | Issue a workload credential |
| `DELETE /projects/{project_id}/capabilities/{kind}/credentials/{credential_id}` | Revoke a workload credential |
| `DELETE /projects/{project_id}/capabilities/{kind}` | Start a confirmed deletion operation |
| `GET /operations/{operation_id}` | Read asynchronous operation status |

Asynchronous changes return an operation ID. The API must apply project authorization to operation lookup as well as resource lookup. Passwords and keys appear only at issuance; metadata, audit records, and ordinary status responses contain references instead of secret values.

## Project data views

The first portal slice would show PostgreSQL connection details and provide an S3 object browser. A project-bound SQL view is optional. Later integrations may use Fauxton, Hubble, Qdrant Web UI, a Valkey administration UI, OpenSearch Dashboards, a ClickHouse SQL console, and NUI only when each can enforce the same project boundary in the browser and in direct API requests. If a native UI cannot provide that boundary, the portal should implement the required project view through the service API.

## Operations and recovery

Metadata and data stores need separate backup and restore procedures. Recovery must reconcile metadata records with actual service resources before resuming jobs. An interrupted provision must yield one usable resource with the intended owner and permissions. Administrative access and public exposure should be tested independently, including a check that the metadata instance is unreachable from outside the lab.

The implementation sequence and measurable release gates are in the [implementation plan](implementation-plan.md).
