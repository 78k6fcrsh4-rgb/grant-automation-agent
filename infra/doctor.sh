#!/usr/bin/env bash
# Why is the backend not starting? Run this in a SECOND terminal while the
# stuck one sits there. Everything is timeout-bounded; it cannot hang.
#
#   ./infra/doctor.sh

BACKEND="$(cd "$(dirname "${BASH_SOURCE[0]}")/../backend" && pwd)"
ok()   { printf '  \033[32mok\033[0m    %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; }
note() { printf '        %s\n' "$1"; }

DB_URL="$(grep -E '^DATABASE_URL=' "$BACKEND/.env" 2>/dev/null | cut -d= -f2-)"
PSQL_URL="${DB_URL/postgresql+psycopg:\/\//postgresql://}"

echo "Port 8000"
if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
    bad "something is already listening on 8000 — a previous run never died"
    lsof -nP -iTCP:8000 -sTCP:LISTEN | tail -n +2 | awk '{print "        pid "$2" ("$1")"}'
    note "kill it:  kill \$(lsof -tiTCP:8000 -sTCP:LISTEN)"
else
    ok "port 8000 is free"
fi

echo
echo "Stray uvicorn processes"
if pgrep -fl "uvicorn app.main" >/dev/null 2>&1; then
    pgrep -fl "uvicorn app.main" | awk '{print "        pid "$1}'
    note "kill them:  pkill -f 'uvicorn app.main'"
else
    ok "none running"
fi

echo
echo "PostgreSQL"
if pg_isready -h localhost -p 5432 -t 5 >/dev/null 2>&1; then
    ok "accepting connections"
else
    bad "not accepting connections on localhost:5432"
    note "brew services start postgresql@16"
fi

echo
echo "Connecting as the app does"
if [ -z "$PSQL_URL" ]; then
    bad "no DATABASE_URL in $BACKEND/.env"
else
    if PGCONNECT_TIMEOUT=8 psql "$PSQL_URL" -tAc 'select current_user, current_database()' 2>/dev/null; then
        ok "the app's credentials work"
    else
        bad "cannot connect with the URL in .env"
        note "psql \"$PSQL_URL\" -c 'select 1'    # to see the real error"
    fi
fi

echo
echo "Blocked queries (the usual cause of a silent hang)"
BLOCKED="$(PGCONNECT_TIMEOUT=8 psql "$PSQL_URL" -tAc "
  SELECT count(*) FROM pg_stat_activity
  WHERE datname = current_database() AND wait_event_type = 'Lock'" 2>/dev/null)"
IDLE_TX="$(PGCONNECT_TIMEOUT=8 psql "$PSQL_URL" -tAc "
  SELECT count(*) FROM pg_stat_activity
  WHERE datname = current_database() AND state = 'idle in transaction'" 2>/dev/null)"
if [ "${BLOCKED:-0}" != "0" ]; then
    bad "$BLOCKED query/queries waiting on a lock"
else
    ok "nothing waiting on a lock"
fi
if [ "${IDLE_TX:-0}" != "0" ]; then
    bad "$IDLE_TX connection(s) idle in transaction — these block DDL"
    note "An open psql session with an unfinished transaction will do this."
    note "Quit that psql, or:"
    note "  psql \"$PSQL_URL\" -c \"SELECT pg_terminate_backend(pid)"
    note "    FROM pg_stat_activity WHERE state='idle in transaction'\""
else
    ok "no idle-in-transaction connections"
fi

echo
echo "Alembic (hangs here mean a database lock, not a code problem)"
cd "$BACKEND" || exit 1
if command -v timeout >/dev/null; then TO="timeout 20"; else TO=""; fi
if $TO python3 -m alembic current 2>&1 | tail -2; then
    ok "alembic responded"
else
    bad "alembic did not finish in 20s — something is holding a lock"
fi
