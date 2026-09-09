#!/usr/bin/env bash
# Is Azure ready for the v2.8.0 roll-up? Read-only: this script inspects and
# reports, it changes nothing.
#
#   az login
#   ./infra/azure-check.sh
#
# Every FAIL line names the command that fixes it. Nothing here should be run
# blind — read the fix before applying it.

set -uo pipefail

RG="${RG:-rg-grantsops}"
BACKEND_APP="${BACKEND_APP:-ca-grants-backend}"
FRONTEND_APP="${FRONTEND_APP:-ca-grants-frontend}"
VAULT="${VAULT:-kvgrantsagent}"
PG_SERVER="${PG_SERVER:-gprospect-db-23605}"
ORG_DB="${ORG_DB:-gma_dupage}"

fails=0
ok()   { printf '  \033[32mok\033[0m    %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fails=$((fails+1)); }
warn() { printf '  \033[33mwarn\033[0m  %s\n' "$1"; }
note() { printf '        %s\n' "$1"; }
head_() { printf '\n\033[1m%s\033[0m\n' "$1"; }

command -v az >/dev/null || { echo "az CLI not found: brew install azure-cli"; exit 1; }
az account show >/dev/null 2>&1 || { echo "not logged in: az login"; exit 1; }
echo "Subscription: $(az account show --query name -o tsv)"

# ---------------------------------------------------------------- database
head_ "PostgreSQL server $PG_SERVER"
SRV="$(az postgres flexible-server show -g "$RG" -n "$PG_SERVER" -o json 2>/dev/null)"
if [ -z "$SRV" ]; then
    bad "server not found in resource group $RG"
    note "az postgres flexible-server list -o table"
else
    ok "found — $(echo "$SRV" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(f"PG {d[\"version\"]}, {d[\"sku\"][\"name\"]}, {d[\"state\"]}")')"
    STATE="$(echo "$SRV" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')"
    [ "$STATE" = "Ready" ] || bad "server state is $STATE, not Ready"
fi

head_ "Firewall"
RULES="$(az postgres flexible-server firewall-rule list -g "$RG" -n "$PG_SERVER" -o json 2>/dev/null)"
if [ -n "$RULES" ]; then
    echo "$RULES" | python3 -c '
import json,sys
rs = json.load(sys.stdin)
if not rs: print("        (no rules at all)")
for r in rs:
    print(f"        {r[\"name\"]}: {r[\"startIpAddress\"]} - {r[\"endIpAddress\"]}")
'
    MYIP="$(curl -s -m 8 https://api.ipify.org || echo "")"
    if [ -n "$MYIP" ]; then
        if echo "$RULES" | grep -q "\"$MYIP\""; then
            ok "this machine ($MYIP) is allowed — you can migrate from here"
        else
            bad "this machine ($MYIP) is NOT allowed; migrations will hang"
            note "az postgres flexible-server firewall-rule create -g $RG -n $PG_SERVER \\"
            note "  --rule-name mac-\$(date +%Y%m%d) --start-ip-address $MYIP --end-ip-address $MYIP"
        fi
    fi
    # Container Apps egress is not a fixed IP unless a VNet is used.
    if echo "$RULES" | grep -q '"0.0.0.0"'; then
        ok "Azure services are allowed to connect (the app can reach the server)"
    else
        bad "no 0.0.0.0 rule — Container Apps will not be able to connect"
        note "Container Apps egress IPs are not stable without a VNet, so the"
        note "app needs the 'allow Azure services' rule, or a private endpoint:"
        note "az postgres flexible-server firewall-rule create -g $RG -n $PG_SERVER \\"
        note "  --rule-name AllowAzureServices --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0"
    fi
fi

head_ "Database $ORG_DB"
if az postgres flexible-server db show -g "$RG" -s "$PG_SERVER" -d "$ORG_DB" >/dev/null 2>&1; then
    ok "exists"
    note "migrated? run, with admin credentials:"
    note "  DATABASE_URL='postgresql+psycopg://<admin>@$PG_SERVER.postgres.database.azure.com:5432/$ORG_DB?sslmode=require' \\"
    note "    python -m alembic current      # expect 0002_audit_log_select (head)"
else
    bad "$ORG_DB does not exist yet"
    note "ADMIN_DATABASE_URL='postgresql://<admin>:<pw>@$PG_SERVER.postgres.database.azure.com:5432/postgres?sslmode=require' \\"
    note "  ./infra/provision-org-database.sh dupage"
fi

# ------------------------------------------------------------ container app
head_ "Backend container app $BACKEND_APP"
APP="$(az containerapp show -g "$RG" -n "$BACKEND_APP" -o json 2>/dev/null)"
if [ -z "$APP" ]; then
    bad "$BACKEND_APP not found"
else
    ok "found"
    echo "$APP" | python3 - "$BACKEND_APP" <<'PY'
import json, sys
d = json.load(sys.stdin)
tmpl = d["properties"]["template"]
scale = tmpl.get("scale", {})
mn, mx = scale.get("minReplicas"), scale.get("maxReplicas")
GREEN, RED, YEL, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

# Grant data lives in one process's memory: two replicas means a generate or
# download request can land on a process that never saw the upload.
if mn == 1 and mx == 1:
    print(f"  {GREEN}ok{OFF}    pinned to a single replica ({mn}/{mx})")
else:
    print(f"  {RED}FAIL{OFF}  replicas are {mn}/{mx} — grant data is per-process memory")
    print(f"        az containerapp update -g {sys.argv[1]} -n {sys.argv[1]} --min-replicas 1 --max-replicas 1")

env = {e["name"]: e for e in tmpl["containers"][0].get("env", [])}
required = {
    "DATABASE_URL":     "the gma_app connection string (Key Vault reference)",
    "SECRET_KEY":       "signs JWTs; unset means a hardcoded public dev value",
    "GMA_PERSISTENCE":  "must be 'linked' to file grants for Perch",
    "AUTO_MIGRATE":     "must be 'false' — the app role cannot CREATE SCHEMA",
    "OPENAI_API_KEY":   "extraction (Key Vault reference)",
}
print()
for name, why in required.items():
    e = env.get(name)
    if not e:
        print(f"  {RED}FAIL{OFF}  {name} is not set — {why}")
        continue
    if "secretRef" in e:
        print(f"  {GREEN}ok{OFF}    {name} -> secret '{e['secretRef']}'")
    else:
        val = e.get("value", "")
        if name == "GMA_PERSISTENCE" and val != "linked":
            print(f"  {RED}FAIL{OFF}  GMA_PERSISTENCE is '{val}', not 'linked'")
        elif name == "AUTO_MIGRATE" and val.lower() not in ("false", "0", "no"):
            print(f"  {RED}FAIL{OFF}  AUTO_MIGRATE is '{val}' — the app cannot migrate as gma_app")
        elif name in ("SECRET_KEY", "DATABASE_URL", "OPENAI_API_KEY"):
            print(f"  {YEL}warn{OFF}  {name} is a literal value, not a Key Vault reference")
        else:
            print(f"  {GREEN}ok{OFF}    {name} = {val}")

demo = env.get("DEMO_MODE", {}).get("value", "")
if demo.lower() == "true":
    print(f"  {YEL}warn{OFF}  DEMO_MODE=true — extraction will be fabricated in production")
PY
fi

head_ "Key Vault $VAULT"
if az keyvault show -n "$VAULT" >/dev/null 2>&1; then
    ok "found"
    for s in OPENAI-API-KEY; do
        az keyvault secret show --vault-name "$VAULT" -n "$s" >/dev/null 2>&1 \
            && ok "secret $s present" || warn "secret $s not found (name may differ)"
    done
    note "add the new ones as secrets rather than literals:"
    note "  az keyvault secret set --vault-name $VAULT -n DATABASE-URL --value '<gma_app url>'"
    note "  az keyvault secret set --vault-name $VAULT -n SECRET-KEY --value \"\$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')\""
else
    bad "vault $VAULT not found"
fi

head_ "Deploy pipeline"
BRANCH="$(git -C "$(dirname "${BASH_SOURCE[0]}")/.." branch --show-current 2>/dev/null)"
note "current branch: ${BRANCH:-unknown}"
note "the workflow deploys on push to main — merging is what ships it"

echo
if [ "$fails" -eq 0 ]; then
    echo "No blocking failures. Read the warns before merging."
else
    echo "$fails blocking item(s) above."
fi
exit "$fails"
