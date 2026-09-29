"""GRANT ALL handed perch_app a cross-tenant destruction path.

Migration 0003 wrote `GRANT ALL ON ALL TABLES IN SCHEMA perch TO perch_app`
as shorthand for "Perch owns its own measurements". ALL includes TRUNCATE,
REFERENCES and TRIGGER, and row-level security does not apply to TRUNCATE.

Measured with two organizations' rows present, as perch_app, in a session
correctly scoped to one of them:

    TRUNCATE perch.program_facts ....... 2 rows before, 0 after
    DELETE FROM perch.program_facts .... 2 rows before, 1 after (correct)

One statement erases every organization's financial and program history,
with the policies fully in force. DELETE, which the policies do constrain,
behaves exactly as intended.

This replaces ALL with what Perch actually does — read, append, supersede —
and asserts on every run that neither app role holds TRUNCATE, REFERENCES or
TRIGGER anywhere in core or perch.

Revision ID: 0007_tighten_perch_grants
Revises: 0006_view_security_invoker
"""
from pathlib import Path

from alembic import op

revision = "0007_tighten_perch_grants"
down_revision = "0006_view_security_invoker"
branch_labels = None
depends_on = None

_SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    op.execute((_SQL_DIR / "0007_tighten_perch_grants.sql").read_text())


def downgrade() -> None:
    # Deliberately does not restore GRANT ALL. Going back to it would hand
    # perch_app the TRUNCATE path again, and a downgrade is not a reason to
    # reopen a hole this size; the explicit grants are a superset of what
    # any released code has ever used.
    op.execute("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA perch "
               "TO perch_app")
