# Configure a Keycloak realm for Storage Lab

Storage Lab uses Keycloak for **authentication**. Project roles (`admin`, `viewer`) and global `platform-admin` grants are stored in the Storage Lab metadata database. These permissions do not require Keycloak roles or role mappings.

This guide covers an existing realm such as `platform` and the current local portal address, `https://localhost:8080`. Replace the URLs below when the portal uses another address. The browser must be able to reach the realm's OIDC endpoints, and the API must be able to reach its JWKS endpoint.

## 1. Check the realm and OIDC endpoints

The public issuer is the full realm URL, for example:

```text
https://identity.eseidinger.de/realms/platform
```

Open `https://identity.eseidinger.de/realms/platform/.well-known/openid-configuration`. Its `issuer` value must match the configured issuer URL **exactly**. Read `jwks_uri` from the same document; for the example realm, the expected URL is:

```text
https://identity.eseidinger.de/realms/platform/protocol/openid-connect/certs
```

Storage Lab accepts only **RS256** signed access tokens. The API verifies the signature and the `iss`, `aud`, `exp`, and `sub` claims. If Keycloak runs behind a reverse proxy, configure its public hostname so that discovery and issued tokens use the same issuer URL. See [Keycloak hostname and discovery](https://www.keycloak.org/server/hostname).

## 2. Create the portal client

Create an OpenID Connect client under **Clients** in the realm with these settings:

| Setting | Value for the local development environment |
| --- | --- |
| Client ID | `storage-lab-portal` |
| Client authentication | **Off** (public browser client, no client secret) |
| Standard flow | **On** (Authorization Code) |
| PKCE method | `S256` |
| Valid redirect URIs | `https://localhost:8080/auth/callback` |
| Valid post logout redirect URIs | `https://localhost:8080` |
| Web origins | `https://localhost:8080` |
| Direct access grants | **Off** |
| Implicit flow | **Off** |

Enter the redirect URI and web origin explicitly; avoid broad wildcards. The portal requests `openid profile email` and derives its login and logout redirect URIs from the current browser origin. For another portal address, use its exact origin for the web origin and post logout redirect URI, and `<origin>/auth/callback` for the login redirect URI. See [Keycloak client, flow, redirect, and logout settings](https://www.keycloak.org/docs/latest/server_admin/).

## 3. Add the API audience to access tokens

Add an **Audience** protocol mapper to the portal client: **Clients → storage-lab-portal → Client scopes → Dedicated scope and mappers for this client → Mappers → Configure a new mapper → Audience**. Labels may differ slightly between Keycloak versions.

| Mapper setting | Value |
| --- | --- |
| Name | `storage-lab-api-audience` |
| Included Custom Audience | `storage-lab-api` |
| Add to access token | **On** |
| Add to ID token | **Off** |

The mapper must apply to every portal sign-in. An optional client scope is insufficient unless the portal explicitly requests it. A separate Keycloak client for the API is not required when using **Included Custom Audience**. The **access token's** `aud` claim must contain `storage-lab-api`; it may be a single value or a list. An ID token alone cannot authorize API requests. See the [Keycloak audience mapper reference](https://www.keycloak.org/admin-api/protocol-mappers) and [server administration guide](https://www.keycloak.org/docs/latest/server_admin/).

## 4. Users and permissions

Users must be able to sign in to the realm. Storage Lab identifies them by the **`iss` + `sub`** pair in a verified access token. A user may create a project and becomes its first project admin. Other project members are added in the portal using their issuer, subject, and project role. Global Platform Admins are managed in the metadata database; [bootstrap the first Platform Admin](development-vm.md#platform-admin-bootstrap) once after deployment.

Neither a `storage-lab-portal-admin` nor a `platform-admin` Keycloak role is needed or sufficient. Changing Keycloak roles does not change Storage Lab permissions.

## 5. Point Storage Lab at the realm

The development inventory, [`ansible/inventory/dev.yml`](../ansible/inventory/dev.yml), already uses the example realm. For another external realm, set the issuer and JWKS URL together when deploying:

```sh
STORAGE_LAB_OIDC_ISSUER=https://identity.example/realms/my-realm \
STORAGE_LAB_OIDC_JWKS_URL=https://identity.example/realms/my-realm/protocol/openid-connect/certs \
ansible-playbook -i ansible/inventory/dev.yml ansible/playbooks/app.yml
```

If the client ID or API audience differs, also set `STORAGE_LAB_OIDC_CLIENT_ID` and `STORAGE_LAB_OIDC_AUDIENCE`. Ansible writes the issuer, audience, and JWKS URL to the API configuration and builds the portal with the issuer and client ID. The playbook does **not** create or modify an external realm or client. Storage Lab does not deploy a local Keycloak server or import a realm.

## 6. Verify the configuration

1. Compare `issuer` and `jwks_uri` in the discovery document with the API configuration.
2. Sign in through the portal and inspect the **access token**: `iss` matches the realm, `aud` contains `storage-lab-api`, `sub` is present, and the JWT header has `alg: RS256`. The `sub` value is also the user ID used for Platform Admin bootstrap.
3. Use the access token to call `GET https://localhost:8080/api/me`, then `GET https://localhost:8080/api/projects`. A `401` means the token is missing or invalid. `/api/me` reports `platform_admin` from the metadata database, independently of Keycloak roles.
4. Check both login and logout in the browser. A login failure before returning to the portal often indicates a redirect URI mismatch. A browser token exchange failure may indicate a missing web origin or PKCE setting. An API `401` often indicates a mismatched issuer, audience, or signature.

The external realm must be managed separately from the Storage Lab deployment. See the [Keycloak server administration guide](https://www.keycloak.org/docs/latest/server_admin/) for the Admin Console settings.
