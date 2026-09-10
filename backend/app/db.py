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

# connect_timeout so an unreachable or wedged server fails in 10s with a
# real error instead of hanging the startup indefinitely with no output.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
    connect_args={"connect_timeout": 10},
)
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
    """Verify connectivity and that the database has been migrated.

    Migrating is deliberately NOT the app's job. The app connects as
    `gma_app`, which owns nothing and cannot CREATE SCHEMA — that is the
    point of the role split, and an application that can rewrite its own
    schema at boot is exactly what it is meant to prevent. Migrations run
    once per organization's database, with admin credentials, via
    infra/provision-org-database.sh.

    AUTO_MIGRATE=true is available for a throwaway local database where
    the app happens to connect as an owner. It is off by default, and it
    will fail loudly rather than usefully if the role cannot create the
    schema.
    """
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    if os.getenv("AUTO_MIGRATE", "false").lower() in ("1", "true", "yes"):
        _run_migrations()
        return

    if not _is_migrated():
        raise RuntimeError(
            "Database is not migrated: core.users does not exist in "
            f"{_safe_target()}.\n"
            "Migrations are an admin operation — the app role cannot run "
            "them. From the repo root:\n"
            "    ./infra/provision-org-database.sh <org-slug>\n"
            "or, with admin credentials:\n"
            "    DATABASE_URL=<admin url> python -m alembic upgrade head"
        )


def _safe_target() -> str:
    """host/database, never the credentials."""
    from sqlalchemy.engine import make_url

    u = make_url(DATABASE_URL)
    return f"{u.host or 'local socket'}/{u.database}"


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
