#!/usr/bin/env bash
# Bring the local stack up from cold, cleanly.
#
#   ./infra/dev-up.sh          # checks, then starts the backend
#   ./infra/dev-up.sh --check  # checks only
#
# Start the frontend separately, in its own terminal:
#   cd frontend && npm run dev

set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$REPO/backend"

say()  { printf '\n\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32mok\033[0m   %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; }
note() { printf '       %s\n' "$1"; }

say "Clearing anything left over from a previous run"
if pgrep -f "uvicorn app.main" >/dev/null 2>&1; then
    pkill -f "uvicorn app.main" && ok "killed stray uvicorn process(es)"
    sleep 1
else
    ok "no stray backend processes"
fi
if lsof -tiTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
    kill "$(lsof -tiTCP:8000 -sTCP:LISTEN)" 2>/dev/null && ok "freed port 8000"
    sleep 1
else
    ok "port 8000 free"
fi

say "PostgreSQL"
if pg_isready -h localhost -p 5432 -t 5 >/dev/null 2>&1; then
    ok "running"
else
    bad "not running"
    note "brew services start postgresql@16"
    exit 1
fi

say "Configuration"
[ -f "$BACKEND/.env" ] || { bad "backend/.env is missing"; exit 1; }
ok "backend/.env present"
[ -f "$REPO/frontend/.env" ] || note "frontend/.env missing (VITE_API_URL=http://localhost:8000)"
[ -x "$BACKEND/.venv/bin/python3" ] || { bad "backend/.venv missing"; \
    note "python3.12 -m venv backend/.venv && source backend/.venv/bin/activate"; \
    note "pip install -r backend/requirements.txt"; exit 1; }
ok "virtualenv present"

say "Database is migrated"
DB_URL="$(grep -E '^DATABASE_URL=' "$BACKEND/.env" | cut -d= -f2-)"
PSQL_URL="${DB_URL/postgresql+psycopg:\/\//postgresql://}"
MIGRATED="$(PGCONNECT_TIMEOUT=8 psql "$PSQL_URL" -tAc "SELECT to_regclass('core.users') IS NOT NULL" 2>/dev/null)"
if [ "$MIGRATED" = "t" ]; then
    ok "core schema present"
    USERS="$(PGCONNECT_TIMEOUT=8 psql "$PSQL_URL" -tAc 'SELECT count(*) FROM core.users' 2>/dev/null)"
    GRANTS="$(PGCONNECT_TIMEOUT=8 psql "$PSQL_URL" -tAc "SELECT count(*) FROM core.grants WHERE deleted_at IS NULL" 2>/dev/null)"
    ok "${USERS:-0} user(s), ${GRANTS:-0} grant(s) on file"
else
    bad "core schema missing — the database is not migrated"
    note "./infra/provision-org-database.sh <org-slug>   (needs ADMIN_DATABASE_URL)"
    exit 1
fi

[ "${1:-}" = "--check" ] && { echo; echo "All checks passed."; exit 0; }

say "Starting the backend on http://127.0.0.1:8000"
note "no --reload: it runs two processes, and a failed start leaves one behind"
note "frontend, in another terminal:  cd frontend && npm run dev"
echo
cd "$BACKEND" || exit 1
exec "$BACKEND/.venv/bin/python3" -m uvicorn app.main:app --port 8000
