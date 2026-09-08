#!/usr/bin/env bash
# Provision one partner organization's database on the shared Postgres server.
#
# The isolation model is the database boundary: one database per organization,
# all on one server. Postgres cannot join across databases without an explicit
# FDW, so a missed tenant filter fails closed ("relation does not exist")
# rather than returning another nonprofit's donor records.
#
# Run this once per organization, from a machine that can reach the server
# (your Mac — the Azure firewall must allow its IP).
#
#   ./provision-org-database.sh dupage
#   ./provision-org-database.sh dupage --admin-url "postgresql://gpadmin:...@host:5432/postgres?sslmode=require"
#
# Reads ADMIN_DATABASE_URL from the environment if --admin-url is not given.
# It must point at the server's ADMIN database (postgres), not at an org's.
#
# Idempotent: re-running against an existing database is a no-op plus a
# migration to head.

set -euo pipefail

SLUG="${1:-}"
if [[ -z "$SLUG" || "$SLUG" == -* ]]; then
    echo "usage: $0 <org-slug> [--admin-url URL]" >&2
    exit 2
fi
shift

ADMIN_URL="${ADMIN_DATABASE_URL:-}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --admin-url) ADMIN_URL="$2"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [[ -z "$ADMIN_URL" ]]; then
    echo "error: set ADMIN_DATABASE_URL or pass --admin-url." >&2
    echo "       It must point at the server's 'postgres' database." >&2
    exit 2
fi

if ! [[ "$SLUG" =~ ^[a-z][a-z0-9_]{1,40}$ ]]; then
    echo "error: slug must be lowercase letters, digits and underscores." >&2
    exit 2
fi

DB="gma_${SLUG}"
BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../backend" && pwd)"

command -v psql >/dev/null || {
    echo "error: psql not found. On macOS: brew install libpq && \\" >&2
    echo "       echo 'export PATH=\"/opt/homebrew/opt/libpq/bin:\$PATH\"' >> ~/.zshrc" >&2
    exit 1
}

# The migration runs with whatever python3 is on PATH, so the backend's
# virtualenv has to be active. Failing here beats failing halfway through,
# with the database created but unmigrated.
python3 -c "import alembic, sqlalchemy, psycopg" 2>/dev/null || {
    echo "error: alembic, sqlalchemy and psycopg must be importable." >&2
    echo "       Activate the backend virtualenv first:" >&2
    echo "         cd backend && python3 -m venv .venv && source .venv/bin/activate" >&2
    echo "         pip install -r requirements.txt" >&2
    exit 1
}

# Roles are cluster-wide and shared by every organization's database, so they
# are created once and reused. Passwords are generated here and printed once —
# put them straight into Key Vault; this script stores nothing.
GMA_PW="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32)"
PERCH_PW="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32)"

echo "==> Ensuring roles exist on the server"
psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gma_app') THEN
        CREATE ROLE gma_app LOGIN PASSWORD '${GMA_PW}';
        RAISE NOTICE 'created role gma_app';
    ELSE
        RAISE NOTICE 'role gma_app already exists — password unchanged';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'perch_app') THEN
        CREATE ROLE perch_app LOGIN PASSWORD '${PERCH_PW}';
        RAISE NOTICE 'created role perch_app';
    ELSE
        RAISE NOTICE 'role perch_app already exists — password unchanged';
    END IF;
END
\$\$;
SQL

echo "==> Ensuring database ${DB} exists"
if psql "$ADMIN_URL" -tAc "SELECT 1 FROM pg_database WHERE datname='${DB}'" | grep -q 1; then
    echo "    ${DB} already exists"
else
    psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -q -c "CREATE DATABASE ${DB}"
    echo "    created ${DB}"
fi

# Swap the database name in the admin URL, preserving any query string
# (sslmode=require on Azure).
ORG_URL="$(python3 - "$ADMIN_URL" "$DB" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit
parts = urlsplit(sys.argv[1])
print(urlunsplit((parts.scheme, parts.netloc, "/" + sys.argv[2], parts.query, parts.fragment)))
PY
)"

echo "==> Migrating ${DB} to head"
cd "$BACKEND_DIR"
DATABASE_URL="${ORG_URL/postgresql:\/\//postgresql+psycopg://}" python3 -m alembic upgrade head

echo
echo "==> Done. Connection strings for ${SLUG} (store in Key Vault, not in a file):"
echo
APP_URL="$(python3 - "$ORG_URL" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit
p = urlsplit(sys.argv[1])
host = p.netloc.split("@")[-1]
print(urlunsplit(("postgresql+psycopg", "gma_app:<PASSWORD>@" + host, p.path, p.query, "")))
PY
)"
echo "    GMA   DATABASE_URL = ${APP_URL}"
echo "    Perch DATABASE_URL = ${APP_URL/gma_app:/perch_app:}"
echo
echo "    gma_app password   : ${GMA_PW}"
echo "    perch_app password : ${PERCH_PW}"
echo
echo "    (Shown only if the role was created just now. If the role already"
echo "     existed, its password is unchanged and these are not it.)"
echo
echo "    Remember: GMA_PERSISTENCE=linked is what makes GMA file grants here."
