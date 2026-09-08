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


def migrate_test_database(url: str) -> None:
    """Bring the throwaway database to head, from a clean slate."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    with engine.connect() as conn:
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
