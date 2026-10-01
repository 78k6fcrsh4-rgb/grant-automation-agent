"""A fiscal year belongs to an organization, not to a deployment.

Perch read PERCH_FY_START_MONTH, one value per deployment. With several
organizations behind one deployment that cannot be right for all of them, and
being wrong is silent: a September report for a July-June organization shows
nine months of revenue as "year to date" when the answer is three. The figure
is plausible and it goes to a funder.

Measured before this: ca-perch had no PERCH_FY_START_MONTH set, so it defaulted
to January, and every DonorPerfect-derived YTD figure in the database was summed
from 1 January whatever DuPage's year actually is.

Applying this changes no figure. The default of 1 is exactly what an unset
PERCH_FY_START_MONTH meant, so each organization keeps the behaviour it had
until somebody sets its real value.

Revision ID: 0008_tenant_fiscal_year
Revises: 0007_tighten_perch_grants
"""
from pathlib import Path

from alembic import op

revision = "0008_tenant_fiscal_year"
down_revision = "0007_tighten_perch_grants"
branch_labels = None
depends_on = None

_SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    op.execute((_SQL_DIR / "0008_tenant_fiscal_year.sql").read_text())


def downgrade() -> None:
    # Dropping the column discards each organization's stated fiscal year,
    # which is a fact about them rather than a detail of this schema -- and
    # the only other copy was an environment variable that no longer exists.
    # A downgrade that loses it would be recovered by guessing.
    raise RuntimeError(
        "Refusing to downgrade: this column holds each organization's own "
        "fiscal year, confirmed with their finance lead, and there is nowhere "
        "else it is written down. If the column genuinely has to go, record "
        "the values first:\n"
        "    SELECT slug, fiscal_year_start_month FROM core.tenants;\n"
        "then drop it by hand."
    )
