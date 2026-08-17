"""Env-based admin auto-seed. Offline."""
import os
import tempfile

_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ["SECRET_KEY"] = "test-secret-bootstrap"

from app.db import init_db, SessionLocal
from app.models.db_models import User, Tenant
from app.services import bootstrap, auth_service


def setup_module(_):
    init_db()


def test_seed_from_env_creates_then_is_idempotent(monkeypatch):
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "seed-admin@newco.example")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "bootstrap-pass-123")
    monkeypatch.setenv("SEED_TENANT_NAME", "New Co")
    monkeypatch.setenv("SEED_TENANT_SLUG", "newco")

    assert bootstrap.seed_from_env() == "created"
    assert bootstrap.seed_from_env() == "exists"  # idempotent

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == "seed-admin@newco.example").first()
        assert u is not None and u.role == "admin"
        assert auth_service.verify_password("bootstrap-pass-123", u.hashed_password)
        t = db.query(Tenant).filter(Tenant.slug == "newco").first()
        assert t is not None and t.name == "New Co"
    finally:
        db.close()


def test_seed_from_env_noop_without_vars(monkeypatch):
    monkeypatch.delenv("SEED_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("SEED_ADMIN_PASSWORD", raising=False)
    assert bootstrap.seed_from_env() is None
