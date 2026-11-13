# Technology decisions

**Status:** Accepted for the initial implementation. The repository has no application code yet, so package versions will be pinned when the applications are scaffolded.

## API and provisioning worker

The API and provisioning worker will be written in **Python**. The API will use **FastAPI** for HTTP routes and OpenAPI output, **Pydantic** for request and response models, **SQLAlchemy** for metadata persistence and transactional job creation, and **Alembic** for versioned metadata schema migrations. The worker remains a separate Python process and shares the domain and persistence models where useful. It will claim jobs from metadata PostgreSQL, so the first implementation does not depend on a separate message broker.

| Library | Initial responsibility |
| --- | --- |
| [FastAPI](https://fastapi.tiangolo.com/tutorial/first-steps/) | HTTP endpoints and OpenAPI contract |
| [Pydantic](https://docs.pydantic.dev/latest/) | Validated API input and output models |
| [SQLAlchemy](https://docs.sqlalchemy.org/en/20/) | Metadata models, queries, and transactions |
| [Alembic](https://alembic.sqlalchemy.org/en/latest/) | Reviewed, versioned database migrations |

The API will validate Keycloak access tokens and enforce local project roles on every relevant route. The exact JWT validation package remains an implementation choice; the required issuer, audience, signature, expiry, and key-rotation behavior is defined in the [architecture](architecture.md#identity-and-authorization).

## Portal

The portal will be a **React** single-page application written in **TypeScript**. **Mantine** is the UI component and styling system. The initial supporting libraries are selected for distinct needs:

| Library | Initial responsibility |
| --- | --- |
| [Vite](https://vite.dev/guide/) | React and TypeScript development server and production build |
| [Mantine](https://mantine.dev/getting-started/) (`@mantine/core`, `@mantine/hooks`, `@mantine/form`, `@mantine/notifications`) | Accessible UI building blocks, theme, forms, and user feedback |
| [React Router](https://reactrouter.com/start/declarative/routing) | Project and capability routes |
| [TanStack Query](https://tanstack.com/query/latest/docs/framework/react/overview) | API reads, mutations, cache invalidation, and operation-status polling |
| [`oidc-client-ts`](https://authts.github.io/oidc-client-ts/index.html) | Browser OIDC Authorization Code with PKCE and user session handling |

The portal will treat the Python API as the source of truth for project permissions and provisioning state. Route guards may improve navigation, but the API must authorize requests independently. Newly issued workload credential values must not be placed in TanStack Query cache, browser persistence, or ordinary status responses; credential issuance views should handle them as one-time values.

## Deployment and dependency management

Ansible is the deployment tool. The existing playbooks provision the [development VM](development-vm.md) and install guest prerequisites. Once the applications exist, Ansible should install or update the API and worker processes, apply Alembic migrations, and deploy the built portal assets. Python and frontend dependencies will be pinned in their respective application lockfiles. Additional libraries should be added for a concrete feature rather than included in the initial stack by default.
