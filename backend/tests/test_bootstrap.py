"""Env-based admin auto-seed. No API key needed; needs TEST_DATABASE_URL."""
import os

from tests.conftest import TEST_DATABASE_URL, migrate_test_database, needs_db

if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["SECRET_KEY"] = "test-secret-bootstrap"
os.environ["AUTO_MIGRATE"] = "false"

from app.db import SessionLocal  # noqa: E402
from app.models.core_models import User, Tenant  # noqa: E402
from app.services import bootstrap, auth_service  # noqa: E402

pytestmark = needs_db


def setup_module(_):
    if TEST_DATABASE_URL:
        migrate_test_database(TEST_DATABASE_URL)


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


def test_seed_users_from_env_creates_named_pilot_user(monkeypatch):
    """The legacy 'member' spelling is still accepted and normalised to 'user'.

    A SEED_USERS value is environment config that may already be deployed,
    so v2.8.0 must not break a pilot login on a word change.
    """
    import json as _json
    monkeypatch.setenv("SEED_TENANT_SLUG", "dupage")
    monkeypatch.setenv("SEED_TENANT_NAME", "DuPage Health Coalition")
    monkeypatch.setenv("SEED_USERS", _json.dumps([
        {"email": "pilot@dupagehealth.org", "password": "Pilot-Pass-2026",
         "name": "Pilot Tester", "role": "member"}
    ]))
    results = bootstrap.seed_users_from_env()
    assert ("pilot@dupagehealth.org", "created") in results
    # idempotent
    assert bootstrap.seed_users_from_env() == [("pilot@dupagehealth.org", "exists")]

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == "pilot@dupagehealth.org").first()
        assert u is not None and u.role == "user" and u.full_name == "Pilot Tester"
        assert auth_service.verify_password("Pilot-Pass-2026", u.hashed_password)
    finally:
        db.close()


def test_seed_users_noop_on_bad_json(monkeypatch):
    monkeypatch.setenv("SEED_USERS", "not json")
    assert bootstrap.seed_users_from_env() == []
