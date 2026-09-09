#!/usr/bin/env bash
# Check everything provision-org-database.sh needs, without hanging.
#
# Every network call is timeout-bounded, so this reports a problem rather
# than sitting there. Run it before the provisioning script:
#
#   ./infra/preflight.sh
#   ADMIN_DATABASE_URL='postgresql://...' ./infra/preflight.sh   # also tests the server
#
# Exits non-zero if anything required is missing.

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$REPO/backend"
fail=0

ok()   { printf '  \033[32mok\033[0m    %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=1; }
note() { printf '        %s\n' "$1"; }

echo "Repo: $REPO"
case "$REPO" in
    *' ') echo "        NOTE: the folder name ends in a space. Always quote paths to it." ;;
esac
echo

echo "Tools"
if command -v python3 >/dev/null; then ok "python3 ($(python3 -V 2>&1))"; else
    bad "python3 not found"; fi

if command -v psql >/dev/null; then ok "psql ($(psql --version 2>&1 | head -1))"; else
    bad "psql not found"
    note "brew install libpq"
    note "echo 'export PATH=\"/opt/homebrew/opt/libpq/bin:\$PATH\"' >> ~/.zshrc && exec zsh"
fi
echo

echo "Backend virtualenv"
if [ -d "$BACKEND/.venv" ]; then
    ok ".venv exists"
    if [ -n "${VIRTUAL_ENV:-}" ]; then ok "a virtualenv is active ($VIRTUAL_ENV)"; else
        bad "no virtualenv active in this shell"
        note "source \"$BACKEND/.venv/bin/activate\""
    fi
else
    bad ".venv does not exist"
    note "cd \"$BACKEND\" && python3 -m venv .venv && source .venv/bin/activate"
    note "pip install -r requirements.txt"
fi

for mod in alembic sqlalchemy psycopg; do
    if python3 -c "import $mod" 2>/dev/null; then ok "$mod importable"; else
        bad "$mod not importable"; fi
done
echo

echo "Database server"
if [ -z "${ADMIN_DATABASE_URL:-}" ]; then
    note "ADMIN_DATABASE_URL not set — skipping the server checks."
    note "Set it to the server's ADMIN database (…/postgres), not an org's."
else
    host="$(python3 - <<'PY'
import os, sys
from urllib.parse import urlsplit
netloc = urlsplit(os.environ["ADMIN_DATABASE_URL"]).netloc
host = netloc.split("@")[-1]
print(host.split(":")[0], (host.split(":") + ["5432"])[1])
PY
)"
    set -- $host
    hostname="$1"; port="$2"
    ok "target: $hostname:$port"

    if python3 -c "import socket,sys; socket.gethostbyname('$hostname')" 2>/dev/null; then
        ok "DNS resolves"
    else
        bad "DNS does not resolve — check the hostname"
    fi

    # A blocked Azure firewall DROPS packets, so an unbounded connect just
    # hangs. This is the check that usually explains "nothing is moving".
    if python3 - "$hostname" "$port" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket(); s.settimeout(8)
s.connect((sys.argv[1], int(sys.argv[2]))); s.close()
PY
    then
        ok "TCP $port reachable"
    else
        bad "cannot open TCP $port within 8s"
        note "Almost always the Azure firewall: the server drops packets from"
        note "unknown addresses, so psql hangs instead of refusing."
        note "Add this machine's IP under the Flexible Server ->"
        note "Networking -> Firewall rules. Your current IP:"
        note "  curl -s https://ifconfig.me"
    fi

    if command -v psql >/dev/null; then
        # PGCONNECT_TIMEOUT so a bad password or a firewall can't hang us.
        if PGCONNECT_TIMEOUT=8 psql "$ADMIN_DATABASE_URL" -tAc 'select 1' >/dev/null 2>&1; then
            ok "psql authenticates"
            db="$(PGCONNECT_TIMEOUT=8 psql "$ADMIN_DATABASE_URL" -tAc 'select current_database()' 2>/dev/null)"
            ok "connected to database: $db"
            case "$db" in
                postgres) : ;;
                *) note "NOTE: expected the admin database 'postgres', got '$db'." ;;
            esac
        else
            bad "psql could not connect or authenticate within 8s"
            note "Check the password, and that the URL ends in /postgres"
        fi
    fi
fi

echo
if [ "$fail" -eq 0 ]; then
    echo "All checks passed. Run: ./infra/provision-org-database.sh <org-slug>"
else
    echo "Fix the FAIL lines above, then re-run this script."
fi
exit "$fail"
