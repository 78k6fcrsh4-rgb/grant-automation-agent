"""Alembic environment.

The connection URL always comes from DATABASE_URL, never from
alembic.ini, because migrations run once per organization's database and
the only thing that differs between them is the connection string.

The version table lives in `core` so a database can be inspected for its
migration state without reaching into public.
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

# Load .env here too. The app puts DATABASE_URL into the environment via
# app/__init__.py before it invokes Alembic, but `alembic upgrade head` run
# by hand — which is what infra/README and the provisioning script tell you
# to do — has no such help, and failed with "DATABASE_URL is not set".
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BACKEND_DIR, ".env"))

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
if not url:
    raise RuntimeError("DATABASE_URL is not set and alembic.ini has no sqlalchemy.url")
if url.startswith("sqlite"):
    raise RuntimeError("SQLite is not supported from v2.8.0; use PostgreSQL.")
config.set_main_option("sqlalchemy.url", url)

from app.db import Base  # noqa: E402
from app.models import core_models  # noqa: E402,F401  (registers the tables)

target_metadata = Base.metadata

VERSION_TABLE_SCHEMA = "core"


def _include_object(obj, name, type_, reflected, compare_to):
    """Autogenerate only ever considers `core`; `perch` belongs to Perch."""
    schema = getattr(obj, "schema", None)
    if type_ == "table" and schema not in (None, "core"):
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_object=_include_object,
        version_table_schema=VERSION_TABLE_SCHEMA,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # The version table lives in `core`, so the schema has to exist
        # before Alembic can stamp anything — including on the very first
        # migration, which is the one that creates it.
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=_include_object,
            version_table_schema=VERSION_TABLE_SCHEMA,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
