"""Views were bypassing row-level security completely.

0005 enabled RLS on the tables and stopped there. A Postgres view runs with
its OWNER's privileges unless security_invoker is set, every view here is
owned by the admin, and the admin bypasses the policies — so each view
returned every organization's rows to anyone allowed to read it, scoped
session or not.

Measured as perch_app with two organizations present, before this fix:

    core.obligations, scoped to DuPage ............ 1 row   (correct)
    core.v_upcoming_obligations, same session ..... 2 rows  (both orgs)
    core.v_upcoming_obligations, no tenant set .... 2 rows

v_upcoming_obligations is what Perch's deadline tracker reads. Every
organization would have seen every other one's deadlines, funders and grant
titles on the app's main screen.

This also adds core.tenant_directory, the one view that is owner-scoped on
purpose: authentication cannot scope a session until it knows which
organization the person belongs to, and an unscoped lookup of core.users
returns nothing under RLS. The directory exposes exactly two columns — slug
and id — so it discloses nothing beyond the organization name the person
just typed into the login form. The user lookup then happens inside the
tenant scope like everything else.

Revision ID: 0006_view_security_invoker
Revises: 0005_row_level_security
"""
from pathlib import Path

from alembic import op

revision = "0006_view_security_invoker"
down_revision = "0005_row_level_security"
branch_labels = None
depends_on = None

_SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

_VIEWS = [
    "core.v_upcoming_obligations", "core.v_extraction_overrides",
    "perch.v_current_finance", "perch.v_current_program",
    "perch.v_current_revenue", "perch.v_program_for_export",
]


def upgrade() -> None:
    op.execute((_SQL_DIR / "0006_view_security_invoker.sql").read_text())


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS core.tenant_directory")
    for view in _VIEWS:
        op.execute(f"ALTER VIEW {view} RESET (security_invoker)")
