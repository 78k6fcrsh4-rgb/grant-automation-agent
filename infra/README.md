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
