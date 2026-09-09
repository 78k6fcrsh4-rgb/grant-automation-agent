"""Grant SELECT on core.audit_log to the app roles.

Filing a grant failed with `permission denied for table audit_log`.
Both roles had INSERT and neither had SELECT, which looked right for an
append-only log — but SQLAlchemy writes

    INSERT INTO core.audit_log (...) VALUES (...) RETURNING id, occurred_at

to collect the server-generated primary key and timestamp, and RETURNING
reads the columns it returns. PostgreSQL therefore requires SELECT, and
refused every audit write, which in turn rolled back every grant.

SELECT does not weaken the invariant that matters: UPDATE and DELETE stay
revoked, so the log remains append-only. Being able to read it is also
what makes it useful to the apps — showing who changed a figure is the
point of recording it.

Revision ID: 0002_audit_log_select
Revises: 0001_core_schema
"""
from alembic import op

revision = "0002_audit_log_select"
down_revision = "0001_core_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT SELECT ON core.audit_log TO gma_app, perch_app")
    # Belt and braces: re-assert that the log cannot be rewritten.
    op.execute("REVOKE UPDATE, DELETE ON core.audit_log FROM gma_app, perch_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON core.audit_log FROM gma_app, perch_app")
