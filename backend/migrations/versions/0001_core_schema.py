"""Create the shared core schema.

Phase 1 of the Perch/GMA integration: identity moves out of the public
schema into `core`, and the grant spine (grants, obligations, documents,
provenance, audit log) is created alongside it.

The DDL lives in migrations/sql/0001_core.sql rather than in op.*
calls, because the same schema is shared with Perch and is easier to
review, and diff against grant-platform/schema.sql, as SQL.

Revision ID: 0001_core_schema
Revises:
"""
from pathlib import Path

from alembic import op

revision = "0001_core_schema"
down_revision = None
branch_labels = None
depends_on = None

_SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    op.execute((_SQL_DIR / "0001_core.sql").read_text())


# Dropped in dependency order by CASCADE. alembic_version also lives in
# `core`, so the schema itself must survive — dropping it would take the
# version table with it and leave Alembic unable to record the downgrade.
_TABLES = [
    "audit_log", "obligation_criteria", "obligations", "grant_workplan_tasks",
    "grant_budget_lines", "grant_contacts", "grant_field_provenance", "grants",
    "documents", "metric_definitions", "funders", "funder_profiles", "users",
    "tenants",
]
_TYPES = [
    "user_role", "metric_sensitivity", "metric_kind", "source_system",
    "obligation_progress", "obligation_kind", "grant_status", "document_kind",
    "extraction_confidence",
]


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS core.v_extraction_overrides")
    op.execute("DROP VIEW IF EXISTS core.v_upcoming_obligations")
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS core.{table} CASCADE")
    for type_name in _TYPES:
        op.execute(f"DROP TYPE IF EXISTS core.{type_name}")
    # Roles are cluster-wide and may be in use by another organization's
    # database on the same server, so they are deliberately not dropped.
