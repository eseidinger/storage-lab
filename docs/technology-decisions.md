# Technology decisions

**Status:** Implemented for the PostgreSQL, object-storage, and document slices.

## API and worker

The API and provisioning worker are written in **Python**. FastAPI provides HTTP routes and OpenAPI output; Pydantic validates request and response data; SQLAlchemy persists metadata and operations; Alembic applies versioned schema changes. The worker is a separate process that claims jobs from metadata PostgreSQL, avoiding a broker dependency while JetStream itself remains a planned capability.

| Library | Current responsibility |
| --- | --- |
| [FastAPI](https://fastapi.tiangolo.com/) | HTTP API and OpenAPI schema |
| [Pydantic](https://docs.pydantic.dev/) | Validated API contracts and settings |
| [SQLAlchemy](https://docs.sqlalchemy.org/) | Metadata models, queries, and transactions |
| [Alembic](https://alembic.sqlalchemy.org/) | Reviewed database migrations |
| [PyJWT](https://pyjwt.readthedocs.io/) | RS256 OIDC access-token and JWKS validation |
| [psycopg](https://www.psycopg.org/psycopg3/docs/) | PostgreSQL administration and live access checks |
| [boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html) | S3 resource and object operations |

The API and worker use separate metadata database roles. Only the worker receives PostgreSQL, RustFS, and CouchDB administrative credentials. Secret values in worker operations are encrypted at rest until the operation succeeds.

## Portal

The portal is a **React** single-page application in **TypeScript**. **Mantine** supplies the component system, forms, and notifications. The supporting libraries each serve a specific part of the application:

| Library | Current responsibility |
| --- | --- |
| [Vite](https://vite.dev/) | Development server and production build |
| [React Router](https://reactrouter.com/) | Project and login callback routes |
| [TanStack Query](https://tanstack.com/query/) | API requests, cache invalidation, and operation polling |
| [`oidc-client-ts`](https://authts.github.io/oidc-client-ts/) | OIDC Authorization Code with PKCE and browser session |
| [Tabler Icons](https://tabler.io/icons) | UI icons |

The API remains authoritative for project permissions. One-time secrets stay in dialog component state and are not put in the query cache.

## Deployment and dependency management

Ansible provisions the VM, builds one image containing the API and portal, applies migrations, and runs the app and Caddy through Podman-backed systemd units. Python dependencies are pinned in `backend/uv.lock` and the deployment `backend/requirements.txt`; frontend dependencies are pinned in `frontend/package-lock.json`. The local development VM uses the Platform Keycloak realm, RustFS, CouchDB, and two PostgreSQL clusters. The development VM uses Caddy internal TLS; a public deployment still needs DNS, a separate inventory, backups, and full browser OIDC verification.
