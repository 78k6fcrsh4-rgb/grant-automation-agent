import json
import os
import sys
import pytest

# Make the backend package importable regardless of where pytest is invoked.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

# From v2.8.0 the app requires PostgreSQL. Tests that need a real database
# skip cleanly when TEST_DATABASE_URL is unset, so `python -m pytest` still
# runs offline with no API key and no infrastructure — it just covers less.
# Point it at a throwaway database, e.g.
#   TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/gma_test
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not set; database tests skipped")

# The application role. Some tests must run the app as gma_app rather than as
# the admin, because the admin bypasses every row-level security policy and a
# tenant-isolation test run that way proves nothing at all.
TEST_APP_DATABASE_URL = os.getenv("TEST_APP_DATABASE_URL")
needs_app_db = pytest.mark.skipif(
    not TEST_APP_DATABASE_URL,
    reason="TEST_APP_DATABASE_URL (the gma_app role) is not set")


# app.db builds its engine once, at import, from DATABASE_URL — so whichever
# test module imported first used to decide which role the whole suite ran
# as. Setting it here, in the file pytest imports before any of them, makes
# that deterministic: the application runs as the application role, exactly
# as it does in production, and fixtures that need the admin ask for it
# explicitly through admin_engine() below.
if TEST_APP_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_APP_DATABASE_URL
elif TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL


def admin_engine():
    """A connection as the admin, for fixtures that must create tenants.

    Creating an organization is an admin operation — core.tenants is
    protected by a policy that a session belonging to no organization cannot
    satisfy — so seeding cannot go through the application role.
    """
    from sqlalchemy import create_engine
    return create_engine(TEST_DATABASE_URL, future=True)


def migrate_test_database(url: str) -> None:
    """Bring the throwaway database to head, from a clean slate."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    with engine.connect() as conn:
        # Both schemas, not just core. Dropping core alone leaves every
        # perch table standing — CASCADE removes the foreign keys that
        # depend on core, not the tables holding them — and the next run
        # of migration 0003 then fails with "relation reporting_periods
        # already exists". That made a second test run against the same
        # database impossible from the moment 0003 landed.
        conn.execute(text("DROP SCHEMA IF EXISTS perch CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS core CASCADE"))
        conn.commit()
    engine.dispose()

    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def proposal_text():
    with open(os.path.join(FIXTURES, "milton_proposal.txt"), encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="session")
def moa_text():
    with open(os.path.join(FIXTURES, "milton_moa.txt"), encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="session")
def expected():
    with open(os.path.join(FIXTURES, "milton_expected.json"), encoding="utf-8") as f:
        return json.load(f)
