#!/usr/bin/env bash
# Add an organization to a shared database.
#
#   ADMIN_DATABASE_URL='postgresql://gpadmin:...@host:5432/grants?sslmode=require' \
#     ./infra/add-organization.sh dupage "DuPage Health Coalition"
#
# This is an admin operation and cannot be anything else. core.tenants is
# protected by a policy comparing against the session's organization, and a
# session that does not yet belong to one cannot satisfy it — so the
# application role cannot create organizations, by design. A service that
# could mint an organization could mint itself access to one.
#
# Idempotent: an organization that already exists is reported and left alone.

set -euo pipefail

SLUG="${1:-}"
NAME="${2:-}"
if [[ -z "$SLUG" || -z "$NAME" ]]; then
    echo "usage: $0 <slug> \"<Organization Name>\"" >&2
    exit 2
fi
if ! [[ "$SLUG" =~ ^[a-z][a-z0-9-]{1,40}$ ]]; then
    echo "error: slug must be lowercase letters, digits and hyphens." >&2
    exit 2
fi

ADMIN_URL="${ADMIN_DATABASE_URL:-}"
if [[ -z "$ADMIN_URL" ]]; then
    echo "error: set ADMIN_DATABASE_URL to the shared database, with admin" >&2
    echo "       credentials. The app role cannot create organizations." >&2
    exit 2
fi

command -v psql >/dev/null || {
    echo "error: psql not found. On macOS: brew install libpq" >&2; exit 1; }

# Fail here, with a readable message, rather than part-way through.
if ! WHO="$(psql "$ADMIN_URL" -tAc "SELECT current_user || '@' || current_database()" 2>&1)"; then
    echo "error: cannot connect with ADMIN_DATABASE_URL." >&2
    echo "       psql said: ${WHO}" >&2
    echo "       - Azure needs ?sslmode=require on the URL." >&2
    echo "       - A password containing @ : / ? # or % must be percent-encoded." >&2
    echo "       - ADMIN_DATABASE_URL may be a stale export from this shell." >&2
    echo "         It persists for the life of the shell, so re-deriving it is" >&2
    echo "         not enough on its own -- re-export it:" >&2
    echo "           export ADMIN_DATABASE_URL=\"\$(./infra/admin-url.sh <the shared database>)\"" >&2
    echo "         Check it before using it:" >&2
    echo "           psql \"\$ADMIN_DATABASE_URL\" -tAc \"SELECT current_user || ' @ ' || current_database()\"" >&2
    exit 1
fi
echo "==> Connected as ${WHO}"

EXISTING="$(psql "$ADMIN_URL" -tAc "SELECT id FROM core.tenants WHERE lower(slug) = lower('${SLUG}')")"
if [[ -n "$EXISTING" ]]; then
    echo "    '${SLUG}' already exists: ${EXISTING}"
    echo "    Nothing to do."
    exit 0
fi

NEW_ID="$(psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -tAc \
    "INSERT INTO core.tenants (name, slug) VALUES ('${NAME//\'/\'\'}', '${SLUG}') RETURNING id")"

echo "==> Created '${NAME}' (${SLUG})"
echo "    tenant id: ${NEW_ID}"
echo
echo "    Next: seed its first user. On the app, set"
echo "      SEED_TENANT_SLUG=${SLUG}"
echo "      SEED_TENANT_NAME=\"${NAME}\""
echo "      SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD"
echo "    and restart, or add users through the admin UI once one exists."
echo
echo "    People log in by naming the organization, so '${SLUG}' is what they"
echo "    will type. Tell them the slug, not the id."
