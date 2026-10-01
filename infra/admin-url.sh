#!/usr/bin/env bash
# Print the Postgres server's ADMIN connection URL, derived from .env.azure.
#
#   export ADMIN_DATABASE_URL="$(./infra/admin-url.sh)"
#   ./infra/provision-org-database.sh platform
#
#   ./infra/admin-url.sh gma_platform    # a specific database rather than postgres
#
# WHY THIS EXISTS
#
# The admin credential is not stored as its own variable. It lives inside
# DATABASE_URL in ~/WorkBench/.env.azure, which points at the gprospect
# database, and every admin task needs the same URL with a different database
# name on the end. Doing that by hand means copying a password out of a file,
# and the file also contains ADMIN_PASSWORD -- which is the application's
# admin USER, not the database's admin ROLE. Picking the wrong one gives
# "password authentication failed for user gpadmin", which reads like a
# credential problem with the credential you meant to use.
#
# So nothing is copied and nothing is chosen: this reads the file and rewrites
# the URL.
#
# It percent-encodes the password, which today's does not need and tomorrow's
# might -- a password containing @ : / ? # or % silently produces a URL that
# parses as something else entirely.
#
# It writes the URL to stdout and nothing else, so it is safe in $( ). It
# warns on stderr if stdout is a terminal, because that prints a live
# credential into your scrollback and your shell history.

set -euo pipefail

ENV_FILE="${AZURE_ENV_FILE:-$HOME/WorkBench/.env.azure}"
TARGET_DB="postgres"
DRIVER="postgresql"

# --sqlalchemy emits postgresql+psycopg://, which alembic needs and psql
# rejects. Without it the two tools want different spellings of the same URL
# and the difference is a sed in a pasted command, which is one more thing to
# get wrong at the point where it matters most.
while [[ $# -gt 0 ]]; do
    case "$1" in
        --sqlalchemy) DRIVER="postgresql+psycopg"; shift ;;
        -*) echo "unknown option: $1" >&2
            echo "usage: $0 [<database>] [--sqlalchemy]" >&2
            exit 2 ;;
        *)  TARGET_DB="$1"; shift ;;
    esac
done

if [[ ! -f "$ENV_FILE" ]]; then
    echo "error: no environment file at ${ENV_FILE}" >&2
    echo "       Set AZURE_ENV_FILE to point at it." >&2
    exit 1
fi

if [[ -t 1 ]]; then
    echo "warning: this prints a live admin credential to your terminal." >&2
    echo "         Use it in a command substitution instead:" >&2
    echo "           export ADMIN_DATABASE_URL=\"\$($0 ${TARGET_DB})\"" >&2
fi

python3 - "$ENV_FILE" "$TARGET_DB" "$DRIVER" <<'PY'
import sys
from urllib.parse import quote, unquote, urlsplit, urlunsplit

env_file, target_db, driver = sys.argv[1], sys.argv[2], sys.argv[3]

raw = None
with open(env_file, encoding="utf-8") as handle:
    for line in handle:
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            raw = line.partition("=")[2].strip().strip('"').strip("'")
            break

if not raw:
    sys.exit(f"error: no DATABASE_URL in {env_file}")

parts = urlsplit(raw)
if not parts.password:
    sys.exit(f"error: DATABASE_URL in {env_file} carries no password")
if not parts.username:
    sys.exit(f"error: DATABASE_URL in {env_file} carries no username")

# Refuse an ambiguous source rather than rewrite it into confident nonsense.
#
# Percent-encoding the password on the way OUT does not help if the password
# was unencoded on the way IN: an @ or a / inside it ends the authority early,
# so urlsplit reads part of the password as the hostname and part of the host
# as the path. Measured, with a password of p@ss/word in the source:
#
#   postgresql://gpadmin:p@ss/word@host.example.com:5432/gprospect
#     -> username gpadmin, password p, hostname ss, path /word@host...
#     -> this script would have printed ...@ss:5432/postgres and the caller
#        would have seen a DNS failure for a host called "ss"
#
# Two cheap checks catch it. A real Azure hostname has a dot in it, and the
# path of a Postgres URL is exactly one segment: the database name.
if "." not in (parts.hostname or ""):
    sys.exit(
        f"error: DATABASE_URL in {env_file} parses to the hostname "
        f"{parts.hostname!r}, which is not a real host.\n"
        f"       The password almost certainly contains an unencoded "
        f"@ : / ? # or %, which ends the URL's authority early.\n"
        f"       Percent-encode it IN THE FILE:\n"
        f"         python3 -c 'import urllib.parse,sys; "
        f"print(urllib.parse.quote(sys.argv[1], safe=\"\"))' '<password>'"
    )
if len([seg for seg in parts.path.split("/") if seg]) > 1:
    sys.exit(
        f"error: DATABASE_URL in {env_file} parses to the path "
        f"{parts.path!r}, which should be a single database name.\n"
        f"       The password almost certainly contains an unencoded / or @."
    )

# unquote before quote, or an already-encoded password is encoded twice.
#
# urlsplit does NOT decode: for a stored password of p%40ss, .password returns
# the literal "p%40ss", and quoting that gives "p%2540ss" -- a URL that parses
# back to "p%40ss" rather than "p@ss", and a server that says "password
# authentication failed" while the file holds exactly the right password.
# Measured, before this line was written.
#
# quote(unquote(x)) is the right shape: idempotent for an encoded password and
# a no-op for a plain alphanumeric one.
def normalise(value: str) -> str:
    return quote(unquote(value), safe="")


# psql, not SQLAlchemy: postgresql+psycopg:// is a driver name psql rejects.
netloc = "{}:{}@{}:{}".format(
    normalise(parts.username),
    normalise(parts.password),
    parts.hostname,
    parts.port or 5432,
)
# sslmode=require is not optional on Azure Flexible Server.
query = parts.query or "sslmode=require"
if "sslmode" not in query:
    query += "&sslmode=require"

print(urlunsplit((driver, netloc, "/" + target_db.lstrip("/"), query, "")))
PY
