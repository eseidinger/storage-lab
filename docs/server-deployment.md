# Deployment on storage-lab.eseidinger.de

The server inventory is [ansible/inventory/server.yml](../ansible/inventory/server.yml). It connects as `root` on SSH port 22 using `~/.ssh/eseidinger_rsa`, installs Docker Engine and Compose from Docker's official APT repository, and deploys the same Compose stack as the development VM. The host must run a supported Ubuntu release with at least 16 vCPUs, 32 GiB RAM, and 80 GiB available storage.

Before deployment:

1. Point the DNS A/AAAA records for `storage-lab.eseidinger.de` at the server. If an AAAA record exists, the server must also be reachable over IPv6.
2. Verify the server's SSH host key through a trusted channel and store it in `.local/server/known_hosts`. For a new server, run `mkdir -p .local/server && ssh-keyscan -t ed25519 storage-lab.eseidinger.de > .local/server/known_hosts`, then compare `ssh-keygen -lf .local/server/known_hosts` with the fingerprint obtained through the server console. The inventory requires this file and strict host-key checking. Confirm that `~/.ssh/eseidinger_rsa` grants root access.
3. Allow inbound TCP 80 and 443 for Caddy and certificate issuance. Allow TCP 22 only from administrator addresses. Allow the service ports below only from intended client networks. The server needs outbound access to Ubuntu and Docker APT repositories, container registries, the OIDC issuer, and ACME services.
4. Configure the Keycloak client `storage-lab-portal` with redirect URI `https://storage-lab.eseidinger.de/auth/callback`, post-logout redirect URI `https://storage-lab.eseidinger.de`, and web origin `https://storage-lab.eseidinger.de`. Its access-token audience must be `storage-lab-api`.

From the repository root, run:

```sh
ansible-playbook -i ansible/inventory/server.yml ansible/playbooks/app.yml
```

The playbook stores server-specific passwords and the credential encryption key under the ignored `.local/server-deploy/` directory on the controller. Back up that directory securely: subsequent deployments reuse it. The development VM uses a separate `.local/deploy/` directory. The server directory also contains a temporary application build archive.

| TCP port | Public endpoint or service |
| --- | --- |
| 80 | Caddy HTTP and ACME challenge |
| 443 | HTTPS portal, API, and project CouchDB gateway |
| 4222 | NATS with TLS |
| 5433 | Application PostgreSQL with TLS |
| 6380 | Valkey with TLS |
| 9443 | HTTPS S3 gateway |
| 9444 | HTTPS ClickHouse gateway |
| 9445 | HTTPS Qdrant gateway |
| 9446 | HTTPS OpenSearch gateway, bound to server loopback only |
| 9447 | HTTPS OpenSearch Dashboards, bound to server loopback only |
| 9448 | HTTPS HugeGraph gateway |

All advertised service URLs use `storage-lab.eseidinger.de`. Caddy obtains public certificates for the HTTPS gateways. PostgreSQL, Valkey, and NATS share a self-signed certificate at `/opt/storage-lab/certs/postgres.crt`, with the public hostname in its subject alternative names. Clients of those services must trust that certificate. It expires after 365 days and currently requires manual renewal.

The Compose file publishes the service ports on the VM, except that this inventory binds ports 9446 and 9447 to `127.0.0.1`. An external firewall manages network access; configure its rules for the intended client networks, especially for PostgreSQL, Valkey, and NATS. UFW on the VM is not part of this deployment. The OpenSearch routes remain intended for development use; do not make ports 9446 and 9447 publicly reachable without an access-control design. This deployment does not set up backups, monitoring, or a secret store.

After deployment, verify:

```sh
curl -fsS https://storage-lab.eseidinger.de/api/health
ssh -i ~/.ssh/eseidinger_rsa root@storage-lab.eseidinger.de \
  'docker compose -f /opt/storage-lab/compose.yaml ps'
```

Bootstrap the first Platform Admin as described in [the development VM guide](development-vm.md#platform-admin-bootstrap), using the same command on the server and the user's OIDC `sub` claim.
