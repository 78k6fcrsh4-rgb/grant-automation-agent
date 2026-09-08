"""Database setup — PostgreSQL, schema-aware.

Phase 1 of the Perch/GMA integration. SQLite is gone: the shared `core`
schema uses citext, enums, partial unique indexes and generated columns,
none of which SQLite has, and Container Apps' ephemeral filesystem meant
the SQLite file never survived a deploy anyway (see infra/README.md).

Alembic owns the schema. Nothing here calls create_all() — the shape of
`core` is defined once, in migrations, because it is shared with Perch
and every organization's database must be migrated identically.
"""
import logging
import os

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

log = logging.getLogger(__name__)

CORE_SCHEMA = "core"

DEFAULT_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/gma"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_URL)

if DATABASE_URL.startswith("sqlite"):
    raise RuntimeError(
        "SQLite is no longer supported (v2.8.0). The shared core schema requires "
        "PostgreSQL. Set DATABASE_URL to a postgresql+psycopg:// connection string."
    )

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

# Every model on this Base lives in the `core` schema, so the ORM and the
# migrations agree without repeating schema= on each table.
Base = declarative_base(metadata=MetaData(schema=CORE_SCHEMA))


def get_db():
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Verify connectivity and that migrations have been applied.

    With AUTO_MIGRATE=true (the default) this runs `alembic upgrade head`
    itself, so a single-replica deploy is self-migrating. Set it to false
    where migrations are run as a separate step in the pipeline.
    """
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    if os.getenv("AUTO_MIGRATE", "true").lower() in ("1", "true", "yes"):
        _run_migrations()
        return

    if not _is_migrated():
        raise RuntimeError(
            "Database is not migrated: core.users is missing. Run "
            "`alembic upgrade head` from the backend directory, or set "
            "AUTO_MIGRATE=true."
        )


def _is_migrated() -> bool:
    with engine.connect() as conn:
        return bool(conn.execute(text("SELECT to_regclass('core.users')")).scalar())


def _run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    ini = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alembic.ini")
    cfg = Config(ini)
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(cfg, "head")
    log.info("Database migrated to head")
