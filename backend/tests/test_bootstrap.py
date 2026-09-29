"""Env-based admin auto-seed. No API key needed; needs TEST_DATABASE_URL."""
import os

import pytest

from tests.conftest import (TEST_DATABASE_URL, admin_engine,
                            migrate_test_database, needs_app_db, needs_db)

os.environ["SECRET_KEY"] = "test-secret-bootstrap"
os.environ["AUTO_MIGRATE"] = "false"

from app.db import SessionLocal  # noqa: E402
from app.models.core_models import User, Tenant  # noqa: E402
from app.services import bootstrap, auth_service  # noqa: E402

pytestmark = [needs_db, needs_app_db]


def _create_organization(slug: str, name: str) -> None:
    """What infra/add-organization.sh does, in one line, as the admin.

    The application role cannot create an organization: core.tenants is
    protected by a policy comparing against the session's organization, and
    a session belonging to none cannot satisfy it. Seeding users into an
    organization that an admin created is the real deployment sequence, so
    it is what these tests do.
    """
    from sqlalchemy import text
    eng = admin_engine()
    with eng.begin() as c:
        c.execute(text("INSERT INTO core.tenants (name, slug) VALUES (:n, :s)"
                       " ON CONFLICT DO NOTHING"), {"n": name, "s": slug})
    eng.dispose()


def setup_module(_):
    if TEST_DATABASE_URL:
        migrate_test_database(TEST_DATABASE_URL)
        _create_organization("newco", "New Co")
        _create_organization("dupage", "DuPage Health Coalition")


def test_seed_from_env_creates_then_is_idempotent(monkeypatch):
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "seed-admin@newco.example")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "bootstrap-pass-123")
    monkeypatch.setenv("SEED_TENANT_NAME", "New Co")
    monkeypatch.setenv("SEED_TENANT_SLUG", "newco")

    assert bootstrap.seed_from_env() == "created"
    assert bootstrap.seed_from_env() == "exists"  # idempotent

    # Verified through the admin, because inspecting every organization's
    # rows is an admin act — an application session is scoped to one and
    # would be refused outright with none set.
    from sqlalchemy import text
    eng = admin_engine()
    with eng.connect() as c:
        row = c.execute(text("SELECT role, hashed_password, tenant_id FROM core.users"
                             " WHERE email = :e"),
                        {"e": "seed-admin@newco.example"}).first()
    eng.dispose()
    assert row is not None and row.role == "admin"
    assert auth_service.verify_password("bootstrap-pass-123", row.hashed_password)
    assert row.tenant_id is not None


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
    from sqlalchemy import text
    eng = admin_engine()
    with eng.connect() as c:
        u = c.execute(text("SELECT role, full_name, hashed_password FROM core.users"
                           " WHERE email = :e"),
                      {"e": "pilot@dupagehealth.org"}).first()
    eng.dispose()
    assert u is not None and u.role == "user" and u.full_name == "Pilot Tester"
    assert auth_service.verify_password("Pilot-Pass-2026", u.hashed_password)


def test_seed_users_noop_on_bad_json(monkeypatch):
    monkeypatch.setenv("SEED_USERS", "not json")
    assert bootstrap.seed_users_from_env() == []


def test_seeding_refuses_when_the_organization_does_not_exist(monkeypatch):
    """The app cannot create organizations, and says so usefully.

    This is the behaviour change that comes with several organizations in
    one database: adding one is an admin operation. A deployment that seeds
    into an organization nobody created should stop with an instruction,
    not with a foreign key error or — worse — quietly succeed.
    """
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "nobody@nowhere.example")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "irrelevant-pass-123")
    monkeypatch.setenv("SEED_TENANT_SLUG", "does-not-exist")
    monkeypatch.setenv("SEED_TENANT_NAME", "Does Not Exist")

    with pytest.raises(bootstrap.OrganizationNotProvisioned) as caught:
        bootstrap.seed_from_env()
    message = str(caught.value)
    assert "does-not-exist" in message
    assert "add-organization.sh" in message, \
        "the error should name the command that fixes it"
