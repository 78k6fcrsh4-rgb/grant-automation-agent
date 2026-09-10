#!/usr/bin/env bash
# Is Azure ready for the v2.8.0 roll-up? Read-only: this script inspects and
# reports, it changes nothing.
#
#   az login
#   ./infra/azure-check.sh
#
# Every FAIL line names the command that fixes it. Nothing here should be run
# blind — read the fix before applying it.
#
# Resource groups are discovered, not assumed. An earlier version hardcoded one
# group for every resource and reported a missing server that in fact existed
# somewhere else.

set -uo pipefail

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

head_ "Subscription"
note "$(az account show --query 'name' -o tsv)  ($(az account show --query 'id' -o tsv))"
SUBS="$(az account list --query 'length(@)' -o tsv 2>/dev/null || echo 1)"
if [ "${SUBS:-1}" -gt 1 ]; then
    warn "$SUBS subscriptions visible — check this is the one holding the grant stack"
    az account list --query '[].{name:name, id:id, current:isDefault}' -o tsv 2>/dev/null | sed 's/^/        /'
    note "switch with: az account set --subscription '<name or id>'"
fi

# ---------------------------------------------------------------- database
head_ "PostgreSQL server $PG_SERVER"
PG_RG="$(az postgres flexible-server list --query "[?name=='$PG_SERVER'].resourceGroup | [0]" -o tsv 2>/dev/null)"
[ "$PG_RG" = "null" ] && PG_RG=""
if [ -n "$PG_RG" ]; then
    SRV="$(az postgres flexible-server show -g "$PG_RG" -n "$PG_SERVER" -o json 2>/dev/null)"
else
    SRV=""
fi

if [ -z "$SRV" ]; then
    bad "server '$PG_SERVER' not found anywhere in this subscription"
    note "flexible servers visible here (name / group / state):"
    az postgres flexible-server list \
        --query '[].{n:name, g:resourceGroup, s:state}' -o tsv 2>/dev/null | sed 's/^/          /'
    note "if the right one is listed, re-run as: PG_SERVER=<name> ./infra/azure-check.sh"
    note "if nothing is listed, the server is in another subscription (see above)"
else
    ok "found in resource group $PG_RG"
    echo "$SRV" > /tmp/azcheck-srv.json
    python3 - /tmp/azcheck-srv.json <<'PYSRV'
import json, sys
d = json.load(open(sys.argv[1]))
print(f"        PG {d.get('version')}, {d.get('sku',{}).get('name')}, state={d.get('state')}")
print(f"        host {d.get('fullyQualifiedDomainName')}")
PYSRV
    rm -f /tmp/azcheck-srv.json
    STATE="$(az postgres flexible-server show -g "$PG_RG" -n "$PG_SERVER" --query state -o tsv 2>/dev/null)"
    [ "$STATE" = "Ready" ] || bad "server state is $STATE, not Ready"
fi

head_ "Firewall"
if [ -z "$PG_RG" ]; then
    warn "skipped — the server was not located"
else
    RULES="$(az postgres flexible-server firewall-rule list -g "$PG_RG" -n "$PG_SERVER" -o json 2>/dev/null)"
    if [ -z "$RULES" ]; then
        warn "could not read firewall rules (permission?)"
    else
        echo "$RULES" > /tmp/azcheck-rules.json
        python3 - /tmp/azcheck-rules.json <<'PYRULES'
import json, sys
rs = json.load(open(sys.argv[1]))
if not rs:
    print("        (no rules at all — nothing can connect)")
for r in rs:
    print(f"        {r['name']}: {r['startIpAddress']} - {r['endIpAddress']}")
PYRULES
        rm -f /tmp/azcheck-rules.json
        MYIP="$(curl -s -m 8 https://api.ipify.org || echo "")"
        if [ -z "$MYIP" ]; then
            warn "could not determine this machine's public IP"
        elif echo "$RULES" | grep -q "\"$MYIP\""; then
            ok "this machine ($MYIP) is allowed — you can migrate from here"
        else
            bad "this machine ($MYIP) is NOT allowed; migrations will hang, not error"
            note "az postgres flexible-server firewall-rule create -g $PG_RG -n $PG_SERVER \\"
            note "  --rule-name mac-\$(date +%Y%m%d) --start-ip-address $MYIP --end-ip-address $MYIP"
        fi
        # Container Apps egress is not a fixed IP unless a VNet is used.
        if echo "$RULES" | grep -q '"0.0.0.0"'; then
            ok "Azure services are allowed to connect (the app can reach the server)"
        else
            bad "no 0.0.0.0 rule — Container Apps will not be able to connect"
            note "Container Apps egress IPs are not stable without a VNet, so the"
            note "app needs the 'allow Azure services' rule, or a private endpoint:"
            note "az postgres flexible-server firewall-rule create -g $PG_RG -n $PG_SERVER \\"
            note "  --rule-name AllowAzureServices --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0"
        fi
    fi
fi

head_ "Database $ORG_DB"
if [ -z "$PG_RG" ]; then
    warn "skipped — the server was not located"
elif az postgres flexible-server db show -g "$PG_RG" -s "$PG_SERVER" -d "$ORG_DB" >/dev/null 2>&1; then
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
APP_RG="$(az containerapp list --query "[?name=='$BACKEND_APP'].resourceGroup | [0]" -o tsv 2>/dev/null)"
[ "$APP_RG" = "null" ] && APP_RG=""
if [ -z "$APP_RG" ]; then
    bad "$BACKEND_APP not found in this subscription"
    note "container apps visible here (name / group):"
    az containerapp list --query '[].{n:name, g:resourceGroup}' -o tsv 2>/dev/null | sed 's/^/          /'
else
    ok "found in resource group $APP_RG"
    APP_JSON="$(mktemp "${TMPDIR:-/tmp}/azcheck-app.XXXXXX")"   # bare -t prefix is BSD-only
    az containerapp show -g "$APP_RG" -n "$BACKEND_APP" -o json > "$APP_JSON" 2>/dev/null
    if [ ! -s "$APP_JSON" ]; then
        bad "could not read $BACKEND_APP definition"
    else
        # The app JSON is passed as a FILE, not on stdin: the here-doc below is
        # itself delivered on stdin, and the two cannot share it. Piping the
        # JSON in while feeding the script by here-doc is what made an earlier
        # version die with JSONDecodeError and skip every check that matters.
        python3 - "$APP_JSON" "$BACKEND_APP" "$APP_RG" <<'PYAPP'
import json, sys
d = json.load(open(sys.argv[1]))
app_name, app_rg = sys.argv[2], sys.argv[3]
tmpl = d["properties"]["template"]
scale = tmpl.get("scale", {}) or {}
mn, mx = scale.get("minReplicas"), scale.get("maxReplicas")
GREEN, RED, YEL, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
bad = 0

# Grant data lives in one process's memory: two replicas means a generate or
# download request can land on a process that never saw the upload.
if mn == 1 and mx == 1:
    print(f"  {GREEN}ok{OFF}    pinned to a single replica ({mn}/{mx})")
else:
    print(f"  {RED}FAIL{OFF}  replicas are {mn}/{mx} — grant data is per-process memory")
    print(f"        az containerapp update -g {app_rg} -n {app_name} --min-replicas 1 --max-replicas 1")
    bad += 1

env = {e["name"]: e for e in tmpl["containers"][0].get("env", []) or []}
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
        bad += 1
        continue
    if "secretRef" in e:
        print(f"  {GREEN}ok{OFF}    {name} -> secret '{e['secretRef']}'")
        continue
    val = e.get("value", "")
    if name == "GMA_PERSISTENCE" and val != "linked":
        print(f"  {RED}FAIL{OFF}  GMA_PERSISTENCE is '{val}', not 'linked'")
        bad += 1
    elif name == "AUTO_MIGRATE" and val.lower() not in ("false", "0", "no"):
        print(f"  {RED}FAIL{OFF}  AUTO_MIGRATE is '{val}' — the app cannot migrate as gma_app")
        bad += 1
    elif name in ("SECRET_KEY", "DATABASE_URL", "OPENAI_API_KEY"):
        print(f"  {YEL}warn{OFF}  {name} is a literal value, not a Key Vault reference")
    else:
        print(f"  {GREEN}ok{OFF}    {name} = {val}")

demo = (env.get("DEMO_MODE", {}) or {}).get("value", "")
if demo.lower() == "true":
    print(f"  {YEL}warn{OFF}  DEMO_MODE=true — extraction will be fabricated in production")

sys.exit(min(bad, 100))
PYAPP
        appfails=$?
        fails=$((fails + appfails))
    fi
    rm -f "$APP_JSON"
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
