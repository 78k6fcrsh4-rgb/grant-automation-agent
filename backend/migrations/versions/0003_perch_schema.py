"""Create the perch schema: reporting periods and the fact tables.

Phase 3 of the Perch/GMA integration. Perch kept its own state in
snapshots.json, which a container filesystem does not survive — every
restart or new revision would have wiped the dashboard. These are the
tables that replace it.

The DDL lives in migrations/sql/0003_perch.sql rather than in op.*
calls, for the same reason as 0001: the schema is shared with Perch and
is easier to review, and to diff against grant-platform/schema.sql, as
SQL.

Note that gma_app is deliberately REVOKEd from everything here. That is
the enforceable form of "no donor or client data ever reaches a prompt":
the service holding the OpenAI credential cannot read a donor label or a
program outcome even by accident.

Revision ID: 0003_perch_schema
Revises: 0002_audit_log_select
"""
from pathlib import Path

from alembic import op

revision = "0003_perch_schema"
down_revision = "0002_audit_log_select"
branch_labels = None
depends_on = None

_SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    op.execute((_SQL_DIR / "0003_perch.sql").read_text())


# Dropped explicitly and in dependency order rather than with
# DROP SCHEMA ... CASCADE. alembic_version lives in `core` so dropping
# `perch` would not take it out, but 0001 learned the habit the hard way
# and an explicit list fails loudly if something unexpected is in there.
_VIEWS = [
    "v_program_for_export", "v_current_program",
    "v_current_finance", "v_current_revenue",
]
_TABLES = [
    "funder_field_aliases", "revenue_facts", "program_facts",
    "finance_facts", "reporting_periods",
]


def downgrade() -> None:
    for view in _VIEWS:
        op.execute(f"DROP VIEW IF EXISTS perch.{view}")
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS perch.{table} CASCADE")
    # The generated column on reporting_periods depends on this, so it
    # can only go after the tables.
    op.execute("DROP FUNCTION IF EXISTS perch.period_label(date)")
    op.execute("DROP SCHEMA IF EXISTS perch")
    # Roles are cluster-wide and may be in use by another organization's
    # database on the same server, so they are deliberately not dropped.
