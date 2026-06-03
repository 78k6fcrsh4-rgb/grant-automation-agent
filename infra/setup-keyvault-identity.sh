#!/usr/bin/env bash
#
# One-time setup: let the backend Container App read OPENAI-API-KEY directly
# from Key Vault using its own system-assigned managed identity.
#
# After this runs, the secret is wired as a Key Vault *reference* on the
# Container App. The value never passes through GitHub Actions, the deploy
# service principal needs no Key Vault access, and key rotations in Key Vault
# are picked up automatically (Container Apps refreshes KV references ~every
# 30 min, and on each new revision).
#
# Run this ONCE from Azure Cloud Shell or any shell with `az login` as an
# account that has BOTH:
#   - Contributor on the Container App (to assign identity / set secrets), and
#   - Owner or User Access Administrator on the vault/RG (to create the role
#     assignment).
#
# Re-running is safe (idempotent).
set -euo pipefail

SUBSCRIPTION="7fce9030-24d6-466a-99d1-835d0238e78b"
RESOURCE_GROUP="rg-grantsops"
BACKEND_APP="ca-grants-backend"
VAULT_NAME="kvgrantsagent"
SECRET_NAME="OPENAI-API-KEY"        # actual name in Key Vault (lookups are case-insensitive)
APP_SECRET_NAME="openai-key"          # Container App secret name
ENV_VAR_NAME="OPENAI_API_KEY"         # env var the backend reads

az account set --subscription "$SUBSCRIPTION"

VAULT_SCOPE="/subscriptions/${SUBSCRIPTION}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.KeyVault/vaults/${VAULT_NAME}"
# Versionless URI -> always resolves to the current secret version (good for rotation).
SECRET_URI="https://${VAULT_NAME}.vault.azure.net/secrets/${SECRET_NAME}"

echo "==> 1/4  Enabling system-assigned managed identity on ${BACKEND_APP}..."
az containerapp identity assign \
  --name "$BACKEND_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --system-assigned \
  --output none

PRINCIPAL_ID="$(az containerapp identity show \
  --name "$BACKEND_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --query principalId -o tsv)"
echo "    identity principalId: ${PRINCIPAL_ID}"

echo "==> 2/4  Granting 'Key Vault Secrets User' on ${VAULT_NAME}..."
# Idempotent: ignore error if the assignment already exists.
az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" \
  --scope "$VAULT_SCOPE" \
  --output none 2>/dev/null || echo "    (role assignment already present)"

echo "==> 3/4  Waiting ~60s for the role assignment to propagate..."
sleep 60

echo "==> 4/4  Wiring the Key Vault reference + env var on ${BACKEND_APP}..."
az containerapp secret set \
  --name "$BACKEND_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --secrets "${APP_SECRET_NAME}=keyvaultref:${SECRET_URI},identityref:system" \
  --output none

az containerapp update \
  --name "$BACKEND_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --set-env-vars "${ENV_VAR_NAME}=secretref:${APP_SECRET_NAME}" \
  --output none

echo
echo "Done. ${BACKEND_APP} now reads ${ENV_VAR_NAME} from Key Vault via its"
echo "managed identity. CI no longer touches the secret. Verify with:"
echo "  az containerapp secret list -n ${BACKEND_APP} -g ${RESOURCE_GROUP} -o table"
