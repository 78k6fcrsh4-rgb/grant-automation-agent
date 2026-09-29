"""Many organizations in one database, separated by row-level security.

This replaces the isolation model everything before it was built on. One
database per organization made separation structural — Postgres cannot join
across databases without an explicit FDW, so a missed tenant filter failed
closed. From here separation is a policy that holds only while every session
sets app.tenant_id correctly.

The DDL lives in migrations/sql/0005_row_level_security.sql, which carries the
full reasoning, including why there is no FORCE and no BYPASSRLS migrator role
(neither is possible with a non-superuser admin, which is what Azure Flexible
Server provides, and FORCE would additionally break Alembic itself).

Verified against Postgres 16 with two tenants holding overlapping data, read
as gma_app and perch_app rather than as the owner:

  - each role sees only its own tenant's grants, obligations, users, tenants
    row, reporting periods and program facts
  - core.grant_field_provenance — a child table with no tenant_id, scoped
    through its parent by EXISTS — isolates correctly in both directions
  - an INSERT naming another tenant is refused by WITH CHECK
  - an UPDATE of another tenant's row affects 0 rows and leaves it unchanged
  - a session with no app.tenant_id set sees nothing at all
  - down and up again leaves 18 policies and no residue

Revision ID: 0005_row_level_security
Revises: 0004_tenant_singleton
"""
from pathlib import Path

from alembic import op

revision = "0005_row_level_security"
down_revision = "0004_tenant_singleton"
branch_labels = None
depends_on = None

_SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

_PROTECTED = [
    "core.users", "core.funders", "core.metric_definitions", "core.documents",
    "core.grants", "core.obligations", "core.audit_log", "core.tenants",
    "core.grant_field_provenance", "core.grant_contacts",
    "core.grant_budget_lines", "core.grant_workplan_tasks",
    "core.obligation_criteria", "perch.reporting_periods",
    "perch.finance_facts", "perch.program_facts", "perch.revenue_facts",
    "perch.funder_field_aliases",
]


def upgrade() -> None:
    op.execute((_SQL_DIR / "0005_row_level_security.sql").read_text())


def downgrade() -> None:
    for table in _PROTECTED:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS core.current_tenant()")

    # Going back means one tenant per database again, and that is only
    # possible if this database still holds one. Refusing loudly beats
    # recreating the index and failing on a bare duplicate-key error, or
    # worse, leaving several organizations in a database whose invariant
    # says there is one.
    op.execute("""
        DO $$
        DECLARE n integer;
        BEGIN
            SELECT count(*) INTO n FROM core.tenants;
            IF n > 1 THEN
                RAISE EXCEPTION
                    'This database holds % tenants. Downgrading restores the '
                    'one-tenant-per-database rule, so every organization but '
                    'one must first be moved to its own database. Separating '
                    'them after the fact is the hard direction — see '
                    'MULTITENANCY-PLAN.md.', n;
            END IF;
            CREATE UNIQUE INDEX IF NOT EXISTS tenants_singleton
                ON core.tenants ((true));
        END
        $$;
    """)
