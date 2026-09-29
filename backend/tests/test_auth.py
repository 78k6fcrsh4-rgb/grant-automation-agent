"""Auth tests — no API key needed, but a throwaway PostgreSQL database is.

From v2.8.0 identity lives in the shared `core` schema, which needs real
Postgres. Set TEST_DATABASE_URL to run these; without it they skip.
"""
import os
import uuid

import pytest

from tests.conftest import (TEST_APP_DATABASE_URL, TEST_DATABASE_URL,
                            admin_engine, migrate_test_database, needs_app_db,
                            needs_db)

# The application runs as gma_app here, not as the admin. These tests include
# one that checks a user of one organization cannot reach another's grant, and
# the admin bypasses every policy — so run as the admin it would pass for the
# wrong reason, or fail for one.
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["LLM_REQUIRED"] = "false"
os.environ["AUTO_MIGRATE"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models.core_models import Tenant, User  # noqa: E402
from app.services import auth_service  # noqa: E402

pytestmark = [needs_db, needs_app_db]


@pytest.fixture(scope="module", autouse=True)
def seed():
    """Two organizations, seeded by the admin because the app cannot.

    Raw SQL rather than the ORM: the ORM session belongs to the application
    engine, which is now gma_app and cannot create an organization at all.
    """
    from sqlalchemy import text
    migrate_test_database(TEST_DATABASE_URL)
    eng = admin_engine()
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    with eng.begin() as c:
        for tid, name, slug in ((t1, "DuPage Health Coalition", "dupage"),
                                (t2, "Other Org", "other")):
            c.execute(text("INSERT INTO core.tenants (id,name,slug)"
                           " VALUES (:i,:n,:s)"), {"i": tid, "n": name, "s": slug})
        for tid, email, name, pw, role in (
                (t1, "admin@dupage.org", "Admin", "dupagepass", "admin"),
                (t1, "member@dupage.org", None, "memberpass", "user"),
                (t2, "admin@other.org", None, "otherpass", "admin")):
            c.execute(text("INSERT INTO core.users (id,tenant_id,email,full_name,"
                           "hashed_password,role,is_active) VALUES"
                           " (:u,:t,:e,:f,:h,:r,true)"),
                      {"u": uuid.uuid4(), "t": tid, "e": email, "f": name,
                       "h": auth_service.hash_password(pw), "r": role})
    eng.dispose()
    yield {"t1": t1, "t2": t2}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _login(client, email, password):
    # Organization first — login cannot scope a session without it, and the
    # same address may exist in more than one organization.
    org = "other" if email.endswith("@other.org") else "dupage"
    r = client.post("/api/auth/login",
                    json={"organization": org, "email": email, "password": password})
    return r


def _token(client, email, password):
    return _login(client, email, password).json()["access_token"]


def test_password_hash_roundtrip():
    h = auth_service.hash_password("s3cret!")
    assert auth_service.verify_password("s3cret!", h)
    assert not auth_service.verify_password("wrong", h)


def test_jwt_roundtrip():
    import uuid
    uid, tid = uuid.uuid4(), uuid.uuid4()
    tok = auth_service.create_access_token(user_id=uid, email="a@b.c", tenant_id=tid, role="admin")
    payload = auth_service.decode_token(tok)
    assert payload["sub"] == str(uid) and payload["tenant_id"] == str(tid)
    assert payload["role"] == "admin"
    assert auth_service.decode_token("garbage") is None


def test_login_success(client):
    r = _login(client, "admin@dupage.org", "dupagepass")
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["access_token"]
    assert body["user"]["email"] == "admin@dupage.org" and body["user"]["role"] == "admin"


def test_login_wrong_password(client):
    assert _login(client, "admin@dupage.org", "nope").status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401
    tok = _token(client, "member@dupage.org", "memberpass")
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200 and r.json()["email"] == "member@dupage.org"


def test_grant_routes_require_auth(client):
    assert client.get("/api/grants/list").status_code == 401


def test_admin_can_create_user_member_cannot(client):
    admin = _token(client, "admin@dupage.org", "dupagepass")
    r = client.post("/api/auth/users",
                    headers={"Authorization": f"Bearer {admin}"},
                    json={"email": "new@dupage.org", "password": "newpass123", "role": "user"})
    assert r.status_code == 201 and r.json()["email"] == "new@dupage.org"

    member = _token(client, "member@dupage.org", "memberpass")
    r2 = client.post("/api/auth/users",
                     headers={"Authorization": f"Bearer {member}"},
                     json={"email": "x@dupage.org", "password": "x123456"})
    assert r2.status_code == 403


def test_tenant_isolation_on_grant_access(client, seed):
    # Simulate a grant owned by tenant 1, then try to read it as tenant 2.
    from app.routes import grant_routes as gr
    from app.models.schemas import GrantData
    gr.grant_data_store["grant-xyz"] = GrantData(raw_text="x")
    gr.grant_tenant["grant-xyz"] = seed["t1"]

    other = _token(client, "admin@other.org", "otherpass")
    r = client.get("/api/grants/data/grant-xyz", headers={"Authorization": f"Bearer {other}"})
    assert r.status_code == 404  # tenant 2 cannot see tenant 1's grant

    dupage = _token(client, "admin@dupage.org", "dupagepass")
    r2 = client.get("/api/grants/data/grant-xyz", headers={"Authorization": f"Bearer {dupage}"})
    assert r2.status_code == 200
