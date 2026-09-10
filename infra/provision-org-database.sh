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
# Generated with python3 rather than `tr </dev/urandom | head -c 32`: head
# closes the pipe after 32 bytes, tr dies of SIGPIPE, and under
# `set -euo pipefail` that kills the script silently, before the first
# echo, with exit 141 and no output at all.
gen_password() {
    python3 -c "import secrets, string; print(''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32)))"
}
GMA_ROLE_CREATED="no"
GMA_PW="$(gen_password)"
PERCH_PW="$(gen_password)"
[ ${#GMA_PW} -eq 32 ] && [ ${#PERCH_PW} -eq 32 ] || {
    echo "error: could not generate role passwords." >&2; exit 1
}

echo "==> Checking the admin connection"
if ! ADMIN_WHO="$(psql "$ADMIN_URL" -tAc "SELECT current_user || '@' || current_database()" 2>&1)"; then
    echo "error: cannot connect with ADMIN_DATABASE_URL." >&2
    echo "       psql said: ${ADMIN_WHO}" >&2
    echo "       - Azure needs ?sslmode=require on the URL." >&2
    echo "       - A password containing @ : / ? # or % must be percent-encoded." >&2
    echo "         python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=\"\"))' '<password>'" >&2
    echo "       - The server firewall must allow this machine's IP." >&2
    exit 1
fi
echo "    connected as ${ADMIN_WHO}"

PRE_EXISTING="$(psql "$ADMIN_URL" -tAc "SELECT 1 FROM pg_roles WHERE rolname='gma_app'")"
[[ "$PRE_EXISTING" == "1" ]] || GMA_ROLE_CREATED="yes"

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
# No pipe here on purpose: `psql | grep -q` lets grep close the pipe on its
# first match, psql dies of SIGPIPE (141), and pipefail reports 141 for the
# whole pipeline — so an existing database reads as missing and the CREATE
# below fails the script under ON_ERROR_STOP. Capture, then compare.
DB_EXISTS="$(psql "$ADMIN_URL" -tAc "SELECT 1 FROM pg_database WHERE datname='${DB}'")"
if [[ "$DB_EXISTS" == "1" ]]; then
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

# Privileges are checked from the admin session, which needs no role password
# and so runs on every invocation — including re-runs against a server whose
# roles already exist. Two production failures yesterday were privilege gaps
# that could not surface because every test ran as the superuser.
echo "==> Verifying least-privilege grants in ${DB}"
psql "$ORG_URL" -v ON_ERROR_STOP=1 -tA <<'SQL'
SELECT CASE WHEN has_table_privilege('gma_app', 'core.grants', 'INSERT')
             AND has_table_privilege('gma_app', 'core.grants', 'SELECT')
            THEN '    ok       gma_app can read and write core.grants'
            ELSE '    MISSING  gma_app cannot read/write core.grants' END;
-- INSERT ... RETURNING reads the columns it returns, so an append-only log
-- still needs SELECT. This exact grant was missing and broke filing.
SELECT CASE WHEN has_table_privilege('gma_app', 'core.audit_log', 'INSERT')
             AND has_table_privilege('gma_app', 'core.audit_log', 'SELECT')
            THEN '    ok       gma_app can append to core.audit_log (INSERT ... RETURNING)'
            ELSE '    MISSING  gma_app needs INSERT *and* SELECT on core.audit_log' END;
SELECT CASE WHEN has_table_privilege('gma_app', 'core.audit_log', 'UPDATE')
              OR has_table_privilege('gma_app', 'core.audit_log', 'DELETE')
            THEN '    PROBLEM  core.audit_log is not append-only for gma_app'
            ELSE '    ok       core.audit_log is append-only (no UPDATE/DELETE)' END;
SELECT CASE WHEN has_table_privilege('perch_app', 'core.obligations', 'SELECT')
            THEN '    ok       perch_app can read core.obligations'
            ELSE '    MISSING  perch_app cannot read core.obligations' END;
SELECT CASE WHEN has_table_privilege('perch_app', 'core.grants', 'INSERT')
            THEN '    PROBLEM  perch_app can write core.grants — it should be read-only there'
            ELSE '    ok       perch_app cannot write core.grants' END;
SQL

if [[ "$GMA_ROLE_CREATED" == "yes" ]]; then
    echo "==> Verifying gma_app can actually log in"
    GMA_TEST_URL="$(python3 - "$ORG_URL" "$GMA_PW" <<'PY'
import sys, urllib.parse
from urllib.parse import urlsplit, urlunsplit
p = urlsplit(sys.argv[1])
host = p.netloc.split("@")[-1]
pw = urllib.parse.quote(sys.argv[2], safe="")
print(urlunsplit(("postgresql", f"gma_app:{pw}@{host}", p.path, p.query, "")))
PY
)"
    if psql "$GMA_TEST_URL" -v ON_ERROR_STOP=1 -tAc "SELECT 1" >/dev/null 2>&1; then
        echo "    ok       gma_app logs in to ${DB}"
    else
        echo "    FAILED   gma_app cannot log in — the app will not start" >&2
        exit 1
    fi
fi

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
