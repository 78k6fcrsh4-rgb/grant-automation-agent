"""One tenant per database, enforced rather than assumed.

Isolation between organizations is the database boundary — one database
per org, so Postgres cannot join across them without an explicit FDW and
a missed filter fails closed. That guarantee holds only while each
database really does contain one organization, and until now that was a
convention rather than a rule.

Several code paths depend on it quietly. pg_storage._tenant_id() resolves
the org with ORDER BY created_at LIMIT 1: with two tenant rows it would
not raise, it would silently attribute Perch's writes to whichever tenant
was seeded first. A unique index on a constant expression makes the
second row impossible instead.

grant-platform/schema.sql carries this commented out, described as the
thing to turn on before there is ever a second organization. This turns
it on.

Revision ID: 0004_tenant_singleton
Revises: 0003_perch_schema
"""
from pathlib import Path

from alembic import op

revision = "0004_tenant_singleton"
down_revision = "0003_perch_schema"
branch_labels = None
depends_on = None

_SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    # The SQL guards first and explains itself if the database already
    # holds more than one tenant, rather than failing with a bare
    # duplicate key error from the index.
    op.execute((_SQL_DIR / "0004_tenant_singleton.sql").read_text())


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS core.tenants_singleton")
