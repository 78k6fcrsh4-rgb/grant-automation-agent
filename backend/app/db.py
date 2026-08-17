"""Database setup — portable SQLAlchemy layer.

Default is a local SQLite file, so the app runs anywhere with zero infra.
Set DATABASE_URL (e.g. a Postgres connection string) to swap backends with no
code change — this is what keeps auth portable across the current Azure and a
future United Way environment.

NOTE for Azure Container Apps: the container filesystem is ephemeral. For SQLite
to persist users across deploys, mount an Azure Files share at ./data (see
infra/README.md). Or point DATABASE_URL at a managed Postgres.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")

if DATABASE_URL.startswith("sqlite"):
    # SQLite needs check_same_thread off for FastAPI's threadpool.
    os.makedirs(os.path.dirname(DATABASE_URL.replace("sqlite:///", "")) or ".", exist_ok=True)
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    from app.models import db_models  # noqa: F401  (register models)
    Base.metadata.create_all(bind=engine)
