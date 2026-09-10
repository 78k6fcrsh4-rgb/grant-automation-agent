# Infrastructure: OpenAI key via Key Vault + managed identity

## How the OpenAI key reaches the backend (the right way)

The backend Container App (`ca-grants-backend`) reads `OPENAI_API_KEY` at
runtime directly from Azure Key Vault (`kvgrantsagent`, secret
`OPENAI-API-KEY`) using its own **system-assigned managed identity**. The
Container App secret is a **Key Vault reference**, not a copied value.

Why this is better than fetching the secret in CI:

- The secret value never passes through GitHub Actions logs or environment.
- The deploy service principal (`AZURE_CREDENTIALS`) needs **no** Key Vault
  access — least privilege.
- Key rotations in Key Vault are picked up automatically (Container Apps
  refreshes Key Vault references roughly every 30 minutes and on each new
  revision). No redeploy required to roll the key.

## One-time setup

Run once, from Azure Cloud Shell or any shell with `az login`, as an account
with Contributor on the Container App **and** Owner / User Access Administrator
on the vault (needed to create the role assignment):

```bash
./infra/setup-keyvault-identity.sh
```

The script:
1. enables the system-assigned managed identity on `ca-grants-backend`,
2. grants that identity the **Key Vault Secrets User** role on `kvgrantsagent`,
3. waits for the assignment to propagate,
4. sets the Container App secret `openai-key` as a versionless Key Vault
   reference and maps it to the `OPENAI_API_KEY` env var.

## What the deploy workflow does now

`.github/workflows/deploy.yml` builds/pushes images and updates the Container
Apps. It no longer touches the secret — that step was removed. Once the
one-time setup above is done, the Key Vault reference persists across deploys.

## Verify

```bash
az containerapp secret list -n ca-grants-backend -g rg-grantsops -o table
az role assignment list \
  --scope /subscriptions/7fce9030-24d6-466a-99d1-835d0238e78b/resourceGroups/rg-grantsops/providers/Microsoft.KeyVault/vaults/kvgrantsagent \
  -o table
```

You should see the `openai-key` secret listed as a Key Vault reference and a
`Key Vault Secrets User` assignment for the Container App's identity.

## Rotating the key

Add a new version of `OPENAI-API-KEY` in Key Vault. Because the reference is
versionless, the app picks it up automatically within ~30 minutes, or
immediately on the next deploy. Nothing in CI or this repo changes.

## Optional: user-assigned identity

If other resources need the same Key Vault access, swap the system-assigned
identity for a user-assigned one: create it, assign it to the app, grant it the
role, and set the secret with `identityref:<identity-resource-id>` instead of
`identityref:system`.

---

# Databases (v2.8.0+)

## The model

One PostgreSQL **database per partner organization**, all on one shared
**server**. Isolation is the database boundary, not an application check:
Postgres cannot join across databases without an explicit FDW, so the class of
bug that would leak one nonprofit's donor records into another's dashboard
fails closed rather than returning rows.

Inside each database:

| Schema | Owner | Contents |
|---|---|---|
| `core` | written by GMA, read by Perch | identity, funders, the metric dictionary, documents, grants, obligations, provenance, audit log |
| `perch` | Perch only (Phase 3) | reporting periods and the fact tables |

Two roles, deliberately asymmetric. `gma_app` has **no access to schema
`perch`** — that revoke is the enforceable form of "no donor or client data
ever reaches a prompt", since GMA is the service holding the OpenAI credential.
`perch_app` may advance a deadline (`progress`, `owner_user_id`,
`submitted_at`) but not invent one. Neither can UPDATE or DELETE the audit log.

## Provisioning a new organization

The script always runs on your own machine. What changes between local and
Azure is only `ADMIN_DATABASE_URL` — which database server it talks to. Prove
it locally first; nothing about the schema, the roles or the migration differs.

### Local first (recommended for a first run)

```bash
brew install postgresql@16
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
exec zsh
brew services start postgresql@16

export ADMIN_DATABASE_URL="postgresql://$USER@localhost:5432/postgres"
./infra/preflight.sh
./infra/provision-org-database.sh dupage
```

Homebrew's Postgres creates a superuser named after your macOS account with
trust auth on localhost, so no password is needed. `postgresql@16` also
supplies the `psql` client you will need for Azure later — installing it
means you do not need `libpq` separately.

To point the apps at it:

```
DATABASE_URL=postgresql+psycopg://gma_app@localhost:5432/gma_dupage      # GMA
PERCH_DATABASE_URL=postgresql+psycopg://perch_app@localhost:5432/gma_dupage
```

### Then Azure, when you are ready to deploy

```bash
export ADMIN_DATABASE_URL='postgresql://<admin>:<pw>@<server>.postgres.database.azure.com:5432/postgres?sslmode=require'
./infra/preflight.sh
./infra/provision-org-database.sh dupage
```

Azure Database for PostgreSQL Flexible Server **drops** packets from unlisted
addresses rather than refusing them, so an unreachable server hangs instead of
erroring. Add your machine's IP under the server -> Networking -> Firewall
rules (`curl -s https://ifconfig.me` gives it; a home ISP will change it every
few weeks, and the symptom is preflight's 8-second TCP timeout coming back).

Creates `gma_dupage`, ensures the two roles exist, runs `alembic upgrade head`,
and prints the connection strings to put in Key Vault. Idempotent — re-running
migrates to head and changes nothing else.

Requires `psql` (`brew install libpq`) and a machine the server's firewall
allows. Add the client IP under **Networking → Firewall rules** on the Flexible
Server if the connection times out.

## Migrations

Alembic owns the schema; nothing calls `create_all`. Migrations run **once per
organization's database**, so they must stay idempotent and must never be
hand-applied.

**Migrating is an admin operation, not the app's job.** The app connects as
`gma_app`, which owns nothing and cannot `CREATE SCHEMA` — that is the point of
the role split, and an application able to rewrite its own schema at boot is
exactly what it exists to prevent. `provision-org-database.sh` migrates with
admin credentials; the app only verifies at startup that the database is at
head, and says what to run if it is not.

`AUTO_MIGRATE` therefore defaults to **false**. Set it true only for a
throwaway local database where the app happens to connect as an owner.

## Note for when GProspect joins

The existing `gprospect` database is one database for the *app*, with an
`org_name` column separating organizations — the opposite of the model above.
When GProspect joins the shared spine (Phase 5), its data needs splitting into
the per-organization databases, and its `org_name` string becomes
`core.tenants`. Worth knowing before it accumulates more rows.
