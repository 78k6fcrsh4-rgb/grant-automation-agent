"""Every tenant-scoped table is protected, and stays protected.

This is the guard against the failure nobody notices: someone adds a table
in six months, forgets the row-level security policy, and one nonprofit's
rows become visible to another. There is no error, no log line, no failing
request — just wrong rows on somebody's screen.

The check is DENY BY DEFAULT. Any table in `core` or `perch` must have RLS
enabled and at least one policy, unless it appears in GLOBAL_TABLES below
with a stated reason. A new table therefore fails this test until someone
has made a deliberate decision about it, and that decision shows up in a
diff a reviewer can see.

Deny-by-default matters more than it looks. The obvious version of this
test — "every table with a tenant_id column must have a policy" — passes
happily for a new table that stores tenant data in some other shape, which
is exactly the table a reviewer is least likely to think about.
"""
import pytest
from sqlalchemy import create_engine, text

from tests.conftest import (TEST_DATABASE_URL, migrate_test_database,
                            needs_db)

pytestmark = needs_db


# Tables that hold no tenant's data, each with the reason it is exempt.
# Adding a name here is a security decision; it should be argued for in the
# pull request, not slipped in to make a red test green.
GLOBAL_TABLES = {
    "core.funder_profiles":
        "Shared reference data: what a given funder calls its metrics. "
        "Belongs to no organization; every tenant reads the same rows.",
    "core.alembic_version":
        "Migration bookkeeping. No tenant dimension, and the app roles "
        "cannot read it at all.",
}


@pytest.fixture(scope="module")
def db():
    migrate_test_database(TEST_DATABASE_URL)
    engine = create_engine(TEST_DATABASE_URL, future=True)
    yield engine
    engine.dispose()


def _tables(engine):
    """Every ordinary table in the tenant schemas, with its RLS state."""
    with engine.connect() as conn:
        return {
            row.name: (row.rls_enabled, row.policy_count)
            for row in conn.execute(text("""
                SELECT n.nspname || '.' || c.relname AS name,
                       c.relrowsecurity              AS rls_enabled,
                       (SELECT count(*) FROM pg_policy p
                         WHERE p.polrelid = c.oid)   AS policy_count
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname IN ('core', 'perch')
                  AND c.relkind = 'r'
                ORDER BY 1
            """)).all()
        }


def test_every_table_is_protected_or_deliberately_exempt(db):
    """The drift guard. A new table fails here until someone decides."""
    unprotected = []
    for name, (rls_enabled, policies) in _tables(db).items():
        if name in GLOBAL_TABLES:
            continue
        if not rls_enabled or policies == 0:
            unprotected.append(
                f"{name} (rls_enabled={rls_enabled}, policies={policies})")

    assert not unprotected, (
        "These tables have no row-level security, so every organization's "
        "rows in them are visible to every other:\n  "
        + "\n  ".join(sorted(unprotected))
        + "\n\nEither add a tenant_isolation policy in a migration, or — if "
          "the table genuinely holds no tenant's data — add it to "
          "GLOBAL_TABLES in this file with the reason. Do not silence this "
          "test without deciding which of those is true."
    )


def test_no_stale_exemptions(db):
    """An exemption for a table that no longer exists hides the next one.

    A renamed table leaves its old name in GLOBAL_TABLES, and the new name
    is then unprotected and unexempted — which the test above would catch.
    But the dead entry also makes the list less trustworthy to read, and a
    reviewer skims a list they do not trust.
    """
    present = set(_tables(db))
    stale = sorted(set(GLOBAL_TABLES) - present)
    assert not stale, (
        f"GLOBAL_TABLES names tables that do not exist: {stale}. "
        "Remove them, and check that whatever replaced them is protected."
    )


def test_no_exempt_table_carries_a_tenant_id(db):
    """An exempt table with a tenant_id column is almost certainly a mistake.

    The column is the strongest available signal that rows belong to one
    organization. If a table has one and is on the exemption list, either
    the exemption is wrong or the column is — and both are worth stopping
    for.
    """
    with db.connect() as conn:
        with_tenant = {
            f"{r.table_schema}.{r.table_name}"
            for r in conn.execute(text("""
                SELECT table_schema, table_name FROM information_schema.columns
                WHERE table_schema IN ('core','perch') AND column_name = 'tenant_id'
            """)).all()
        }
    contradictions = sorted(with_tenant & set(GLOBAL_TABLES))
    assert not contradictions, (
        f"Exempt from row-level security but carrying tenant_id: "
        f"{contradictions}. Either it holds one organization's rows and "
        f"needs a policy, or the column should not be there."
    )


def test_app_roles_cannot_bypass_row_level_security(db):
    """With every organization in one database, BYPASSRLS is total access.

    Migration 0005 asserts this too, but a migration runs once. A role
    granted the attribute afterwards would go unnoticed until someone read
    pg_roles; this fails the build instead.
    """
    with db.connect() as conn:
        offenders = [
            f"{r.rolname} (superuser={r.rolsuper}, bypassrls={r.rolbypassrls})"
            for r in conn.execute(text("""
                SELECT rolname, rolsuper, rolbypassrls FROM pg_roles
                WHERE rolname IN ('gma_app', 'perch_app')
                  AND (rolsuper OR rolbypassrls)
            """)).all()
        ]
    assert not offenders, (
        "These application roles can read every organization's data "
        f"regardless of policy: {offenders}"
    )


def test_the_tenant_function_fails_closed(db):
    """No tenant set must mean no rows, not all rows.

    core.current_tenant() returns NULL when app.tenant_id is unset, and
    `tenant_id = NULL` is NULL rather than true — so the policies filter
    everything out. This asserts the NULL, which is the part the policies
    depend on.
    """
    with db.connect() as conn:
        unset = conn.execute(text("SELECT core.current_tenant()")).scalar()
        assert unset is None, (
            "core.current_tenant() returned a value with no app.tenant_id "
            "set. Every policy compares against it, so a non-NULL default "
            "here would silently scope every unscoped session to one "
            "organization."
        )
