#!/usr/bin/env bash
# Delete every row belonging to one organization, keeping the organization.
#
#   ADMIN_DATABASE_URL='postgresql://gpadmin:...@host:5432/grants?sslmode=require' \
#     ./infra/delete-org-data.sh dupage "DuPage Health Coalition"
#     ./infra/delete-org-data.sh dupage "DuPage Health Coalition" --commit
#
# Dry run by default: it does the whole deletion inside a transaction, prints
# the before and after counts, and then rolls back. Nothing is removed until
# --commit. Read the dry run before passing it.
#
# WHAT IS DELETED
#
# Everything the organization owns: its measurements, reporting periods and
# metric definitions; its grants and, by cascade, their obligations, criteria,
# budget lines, contacts, field provenance and workplan tasks; its documents
# and funders; its users; and its audit log.
#
# WHAT IS KEPT
#
# The core.tenants row itself -- name, slug and fiscal_year_start_month -- so
# the organization survives as an empty tenant and does not have to be
# re-added with a new id. Also kept: every other organization, and the global
# core.funder_profiles lookup, which is not any one organization's.
#
# By default the active administrator logins are carried across the deletion
# with their password hashes unchanged, so the organization stays reachable and
# nobody has to reset a password. --delete-all-users removes those too, which
# leaves an organization nobody can sign in to.
#
# THE AUDIT LOG, DELIBERATELY
#
# core.audit_log's foreign keys to tenants, users and documents are NO ACTION
# rather than CASCADE, specifically so that an audit trail cannot be discarded
# as a side effect of deleting something else. Deleting it is a decision, and
# this script is where that decision gets made explicitly. There is no
# --keep-audit-log: the log references users and documents, so keeping it would
# mean keeping those too, and the result would not be an empty tenant.
#
# This is an admin operation. Row-level security does NOT apply to the admin
# role, so the tenant_id predicates in the SQL below are the only thing
# separating this from every organization's data. That is why the id is
# resolved once, and why the script refuses unless the slug and the name
# given on the command line describe the same single organization.

set -euo pipefail

SLUG="${1:-}"
NAME="${2:-}"
if [[ -z "$SLUG" || -z "$NAME" ]]; then
    echo "usage: $0 <slug> \"<Organization Name>\" [--commit] [--delete-all-users]" >&2
    echo "       Both are required: the name is checked against the slug so a" >&2
    echo "       mistyped slug refuses rather than empties the wrong charity." >&2
    exit 2
fi
shift 2 || true

COMMITTING=no
RESTORE=yes
while [[ $# -gt 0 ]]; do
    case "$1" in
        --commit)            COMMITTING=yes; shift ;;
        --delete-all-users)  RESTORE=no; shift ;;
        *)
            echo "unknown argument: $1" >&2
            echo "usage: $0 <slug> \"<Organization Name>\" [--commit] [--delete-all-users]" >&2
            exit 2 ;;
    esac
done

ADMIN_URL="${ADMIN_DATABASE_URL:-}"
if [[ -z "$ADMIN_URL" ]]; then
    echo "error: set ADMIN_DATABASE_URL to the shared database, with admin" >&2
    echo "       credentials. The app role cannot do this: the policies hide" >&2
    echo "       other organizations' rows from it, which is the point." >&2
    echo "         export ADMIN_DATABASE_URL=\"\$(./infra/admin-url.sh <database>)\"" >&2
    exit 2
fi

command -v psql >/dev/null || {
    echo "error: psql not found. On macOS: brew install libpq" >&2; exit 1; }

if ! WHO="$(psql "$ADMIN_URL" -tAc "SELECT current_user || ' @ ' || current_database()" 2>&1)"; then
    echo "error: cannot connect with ADMIN_DATABASE_URL." >&2
    echo "       psql said: ${WHO}" >&2
    echo "       ADMIN_DATABASE_URL may be a stale export from this shell --" >&2
    echo "       it persists for the life of the shell, so re-deriving it is" >&2
    echo "       not enough on its own. Re-export it:" >&2
    echo "         export ADMIN_DATABASE_URL=\"\$(./infra/admin-url.sh <database>)\"" >&2
    exit 1
fi
echo "connected as ${WHO}"

if [[ "$COMMITTING" == yes ]]; then
    echo
    echo "About to permanently delete all data for '${NAME}' (${SLUG})."
    echo "This cannot be undone and there is no soft-delete involved: the rows"
    echo "are gone, including the audit log."
    if [[ "$RESTORE" == no ]]; then
        echo "--delete-all-users was given, so the administrator logins go too"
        echo "and nobody will be able to sign in to this organization."
    fi
    printf "Type the organization's slug to confirm: "
    read -r TYPED
    if [[ "$TYPED" != "$SLUG" ]]; then
        echo "error: typed '${TYPED}', expected '${SLUG}'. Nothing was deleted." >&2
        exit 1
    fi
    FINAL="COMMIT;"
else
    FINAL="ROLLBACK;"
fi

# Every count in the report, as one psql variable, so the identical query runs
# before and after and the two can be compared line by line.
read -r -d '' ROWS <<'ROWSQL' || true
SELECT * FROM (
  SELECT 'core.audit_log' AS tbl, count(*) FROM core.audit_log WHERE tenant_id = (SELECT id FROM target)
  UNION ALL SELECT 'core.documents', count(*) FROM core.documents WHERE tenant_id = (SELECT id FROM target)
  UNION ALL SELECT 'core.funders', count(*) FROM core.funders WHERE tenant_id = (SELECT id FROM target)
  UNION ALL SELECT 'core.grants', count(*) FROM core.grants WHERE tenant_id = (SELECT id FROM target)
  UNION ALL SELECT 'core.metric_definitions', count(*) FROM core.metric_definitions WHERE tenant_id = (SELECT id FROM target)
  UNION ALL SELECT 'core.obligations', count(*) FROM core.obligations WHERE tenant_id = (SELECT id FROM target)
  UNION ALL SELECT 'core.users', count(*) FROM core.users WHERE tenant_id = (SELECT id FROM target)
  UNION ALL SELECT 'core.obligation_criteria', count(*) FROM core.obligation_criteria c
      WHERE EXISTS (SELECT 1 FROM core.obligations o WHERE o.id = c.obligation_id AND o.tenant_id = (SELECT id FROM target))
  UNION ALL SELECT 'core.grant_budget_lines', count(*) FROM core.grant_budget_lines x
      WHERE EXISTS (SELECT 1 FROM core.grants g WHERE g.id = x.grant_id AND g.tenant_id = (SELECT id FROM target))
  UNION ALL SELECT 'core.grant_contacts', count(*) FROM core.grant_contacts x
      WHERE EXISTS (SELECT 1 FROM core.grants g WHERE g.id = x.grant_id AND g.tenant_id = (SELECT id FROM target))
  UNION ALL SELECT 'core.grant_field_provenance', count(*) FROM core.grant_field_provenance x
      WHERE EXISTS (SELECT 1 FROM core.grants g WHERE g.id = x.grant_id AND g.tenant_id = (SELECT id FROM target))
  UNION ALL SELECT 'core.grant_workplan_tasks', count(*) FROM core.grant_workplan_tasks x
      WHERE EXISTS (SELECT 1 FROM core.grants g WHERE g.id = x.grant_id AND g.tenant_id = (SELECT id FROM target))
  UNION ALL SELECT 'perch.reporting_periods', count(*) FROM perch.reporting_periods WHERE tenant_id = (SELECT id FROM target)
  UNION ALL SELECT 'perch.finance_facts', count(*) FROM perch.finance_facts WHERE tenant_id = (SELECT id FROM target)
  UNION ALL SELECT 'perch.program_facts', count(*) FROM perch.program_facts WHERE tenant_id = (SELECT id FROM target)
  UNION ALL SELECT 'perch.revenue_facts', count(*) FROM perch.revenue_facts WHERE tenant_id = (SELECT id FROM target)
  UNION ALL SELECT 'perch.funder_field_aliases', count(*) FROM perch.funder_field_aliases a
      WHERE EXISTS (SELECT 1 FROM core.metric_definitions m WHERE m.id = a.metric_id AND m.tenant_id = (SELECT id FROM target))
) r ORDER BY tbl
ROWSQL

# -f - rather than -c, because psql expands :variables only when the SQL
# arrives on stdin or from a file. The same mistake with -c produced an
# organization literally named :'name' once.
psql "$ADMIN_URL" -v ON_ERROR_STOP=1 \
     -v slug="$SLUG" -v expect_name="$NAME" -v restore="$RESTORE" \
     -v rows="$ROWS" -f - <<SQL
BEGIN;

-- psql does not substitute :variables inside a dollar-quoted block, so the
-- values the assertions need are pinned into a table the block reads.
CREATE TEMP TABLE expectation ON COMMIT DROP AS
SELECT :'slug'::text AS slug, :'expect_name'::text AS name,
       :'restore'::text AS restore;

CREATE TEMP TABLE target ON COMMIT DROP AS
SELECT t.id, t.name, t.slug, t.fiscal_year_start_month
  FROM core.tenants t JOIN expectation e ON e.slug = t.slug;

DO \$\$
DECLARE n int; nm text; want text; wslug text;
BEGIN
  SELECT slug, name INTO wslug, want FROM expectation;
  SELECT count(*) INTO n FROM target;
  IF n <> 1 THEN
    RAISE EXCEPTION
      'expected exactly one organization with slug %, found %. Refusing.',
      wslug, n;
  END IF;
  SELECT name INTO nm FROM target;
  IF nm <> want THEN
    RAISE EXCEPTION 'slug % is the organization "%", not "%". Refusing.',
      wslug, nm, want;
  END IF;
END \$\$;

\echo ''
\echo '=== organization ==='
SELECT name, slug, id AS tenant_id, fiscal_year_start_month AS fy_start
  FROM target;

\echo ''
\echo '=== rows before ==='
:rows;

-- Carried across the deletion with the hash unchanged, so existing passwords
-- keep working. No password is read, printed or reset. Empty when
-- --delete-all-users was given, which is what the predicate on restore does.
CREATE TEMP TABLE restore_admins ON COMMIT DROP AS
SELECT email, full_name, hashed_password, role, is_active
  FROM core.users
 WHERE tenant_id = (SELECT id FROM target)
   AND role = 'admin' AND is_active
   AND (SELECT restore FROM expectation) = 'yes';

\echo ''
\echo '=== deleting, children first ==='

-- First, because its foreign keys to tenants, users and documents are
-- NO ACTION: nothing else can go while these rows still point at it.
DELETE FROM core.audit_log WHERE tenant_id = (SELECT id FROM target);

-- Measurements. Each fact references a period, metric, grant, document and
-- user by NO ACTION, so all of those have to outlive it.
DELETE FROM perch.finance_facts WHERE tenant_id = (SELECT id FROM target);
DELETE FROM perch.program_facts WHERE tenant_id = (SELECT id FROM target);
DELETE FROM perch.revenue_facts WHERE tenant_id = (SELECT id FROM target);

-- This one statement also removes, by CASCADE: obligations and their
-- criteria, budget lines, contacts, field provenance, workplan tasks.
-- Grants reference documents, funders and users by NO ACTION, so grants
-- go before all three.
DELETE FROM core.grants WHERE tenant_id = (SELECT id FROM target);

-- Any obligation not reached through a grant above.
DELETE FROM core.obligations WHERE tenant_id = (SELECT id FROM target);

-- Cascades to this organization's rows in perch.funder_field_aliases.
DELETE FROM core.metric_definitions WHERE tenant_id = (SELECT id FROM target);

DELETE FROM perch.reporting_periods WHERE tenant_id = (SELECT id FROM target);

-- Metadata only: filename, size, sha256, extraction flags. There is no
-- stored file path on this table, so nothing is orphaned outside the
-- database by deleting it.
DELETE FROM core.documents WHERE tenant_id = (SELECT id FROM target);

DELETE FROM core.funders WHERE tenant_id = (SELECT id FROM target);

DELETE FROM core.users WHERE tenant_id = (SELECT id FROM target);

INSERT INTO core.users (tenant_id, email, full_name, hashed_password, role, is_active)
SELECT (SELECT id FROM target), email, full_name, hashed_password, role, is_active
  FROM restore_admins;

DO \$\$
DECLARE n int; r text;
BEGIN
  SELECT count(*) INTO n FROM restore_admins;
  SELECT restore INTO r FROM expectation;
  IF n = 0 AND r = 'yes' THEN
    RAISE WARNING 'This organization had no active administrator, so none was '
                  'restored and it now has no users at all. Nobody can sign in '
                  'to it or get a token until a user row is added.';
  ELSIF n = 0 THEN
    RAISE WARNING '--delete-all-users was given: this organization now has no '
                  'users and nobody can sign in to it.';
  END IF;
END \$\$;

\echo ''
\echo '=== rows after ==='
:rows;

\echo ''
\echo '=== users, passwords unchanged ==='
SELECT email, role::text AS role, is_active FROM core.users
 WHERE tenant_id = (SELECT id FROM target) ORDER BY email;

\echo ''
\echo '=== the organization itself, kept ==='
SELECT name, slug, fiscal_year_start_month AS fy_start FROM core.tenants
 WHERE id = (SELECT id FROM target);

${FINAL}
SQL

echo
if [[ "$COMMITTING" == yes ]]; then
    echo "Committed. The organization remains, with no data."
else
    echo "Dry run: rolled back, nothing was deleted."
    echo "Re-run with --commit to delete for real."
fi
