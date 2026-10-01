#!/usr/bin/env bash
# Add an organization to a shared database.
#
#   ADMIN_DATABASE_URL='postgresql://gpadmin:...@host:5432/grants?sslmode=require' \
#     ./infra/add-organization.sh dupage "DuPage Health Coalition"
#     ./infra/add-organization.sh dupage "DuPage Health Coalition" --fiscal-year-start 7
#
# --fiscal-year-start is the month the organization's fiscal year begins, 1 to
# 12. It defaults to 1 (January) because that is what the old deployment-wide
# PERCH_FY_START_MONTH meant when unset, so nothing changes silently -- but a
# default is not an answer. Perch computes every year-to-date figure from this,
# and a July-June organization left on January reports nine months of revenue
# as "year to date" when the truth is three. Nothing throws. Confirm it in
# writing with their finance lead before their first report.
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
    echo "usage: $0 <slug> \"<Organization Name>\" [--fiscal-year-start N]" >&2
    exit 2
fi
shift 2 || true

FY_START=1
while [[ $# -gt 0 ]]; do
    case "$1" in
        --fiscal-year-start)
            FY_START="${2:-}"; shift 2 ;;
        *)
            echo "unknown argument: $1" >&2
            echo "usage: $0 <slug> \"<Organization Name>\" [--fiscal-year-start N]" >&2
            exit 2 ;;
    esac
done

if ! [[ "$SLUG" =~ ^[a-z][a-z0-9-]{1,40}$ ]]; then
    echo "error: slug must be lowercase letters, digits and hyphens." >&2
    exit 2
fi
# Checked here as well as by the CHECK constraint, so a typo is a usage error
# rather than a database error halfway through.
if ! [[ "$FY_START" =~ ^([1-9]|1[0-2])$ ]]; then
    echo "error: --fiscal-year-start must be a month from 1 to 12, got '${FY_START}'." >&2
    echo "       1 = January, 7 = July. Confirm it with the organization's" >&2
    echo "       finance lead: every year-to-date figure is computed from it." >&2
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

# The SQL arrives on stdin, not through -c, and the values arrive as psql
# variables interpolated with :'slug'. Two things forced that shape, both
# confirmed by running it rather than reading it:
#
#   psql does not expand variables in a -c command at all. With -c, :'slug'
#   reaches the server literally and it reports a syntax error at ":".
#
#   -tAc is a cluster whose c takes the next argument as the command, so
#   "psql -tAc -v slug=x SQL" ran "-v slug=x" as the statement and discarded
#   the SQL with a warning.
#
# What this replaced was worse than either: the name was pasted into the SQL by
# the shell, with apostrophes doubled by a ${NAME//...} expansion that does not
# work inside double quotes -- a backslash before a single quote is not an
# escape there, so the backslashes survived into the statement and
# "Deborah's Place" arrived as 'Deborah\'\'s Place'. Every organisation with an
# apostrophe in its name failed, and any name with a quote in it was an
# injection. Letting psql do the quoting fixes both at once.
EXISTING="$(psql "$ADMIN_URL" -v slug="$SLUG" -tA -f - <<'SQL' | head -1
SELECT id FROM core.tenants WHERE lower(slug) = lower(:'slug');
SQL
)"
if [[ -n "$EXISTING" ]]; then
    echo "    '${SLUG}' already exists: ${EXISTING}"
    echo "    Nothing to do."
    exit 0
fi

# Values go in as psql variables, interpolated with :'name', rather than being
# pasted into the SQL by the shell.
#
# The previous version doubled apostrophes itself with a ${NAME//...} expansion,
# and that does not work: the expansion sits inside a double-quoted string,
# where a backslash before a single quote is not an escape, so the backslashes
# survived into the statement. "Deborah's Place" reached Postgres as
# 'Deborah\'\'s Place' and failed with a syntax error -- so did every other
# organisation whose name contains an apostrophe, which is a great many
# nonprofits.
#
# :'name' and :'slug' make psql do the quoting. That is also the only version of
# this that is not an injection waiting for a name with a quote in it.
#
# head -1: psql prints the command tag ("INSERT 0 1") after the returned row,
# and without it the id carries that text into every message below.
NEW_ID="$(psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -v name="$NAME" -v slug="$SLUG" -v fy="$FY_START" -tA -f - <<'SQL' | head -1
INSERT INTO core.tenants (name, slug, fiscal_year_start_month)
VALUES (:'name', :'slug', :'fy'::smallint) RETURNING id;
SQL
)"

MONTHS=(x January February March April May June July August September October November December)
echo "==> Created '${NAME}' (${SLUG})"
echo "    tenant id:    ${NEW_ID}"
echo "    fiscal year:  starts ${MONTHS[$FY_START]} (month ${FY_START})"
if [[ "$FY_START" == "1" ]]; then
    echo "                  that is the DEFAULT, not a confirmed answer. If this"
    echo "                  organization runs July-June or anything else, fix it"
    echo "                  before their first report:"
    echo "                    UPDATE core.tenants SET fiscal_year_start_month = 7"
    echo "                     WHERE slug = '${SLUG}';"
fi
echo
echo "    Next: seed its first user. On the app, set"
echo "      SEED_TENANT_SLUG=${SLUG}"
echo "      SEED_TENANT_NAME=\"${NAME}\""
echo "      SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD"
echo "    and restart. SEED_USERS takes a JSON list for more than one:"
echo "      [{\"email\":\"jane@example.org\",\"password\":\"...\",\"name\":\"Jane Doe\",\"role\":\"user\"}]"
echo
echo "    THERE IS NO ADMIN UI FOR USERS. This line used to say there was."
echo "    POST /api/auth/users exists and is admin-guarded, but no page in the"
echo "    frontend calls it, so adding a user means SEED_USERS and a restart, a"
echo "    curl to that endpoint with an admin's token, or an INSERT as admin."
echo
echo "    People log in by naming the organization, so '${SLUG}' is what they"
echo "    will type. Tell them the slug, not the id."
