"""Auth tests — all offline, no API key. Uses a throwaway SQLite DB."""
import os
import tempfile

# Configure a temp DB + deterministic secret BEFORE importing the app.
_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["LLM_REQUIRED"] = "false"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal, init_db
from app.models.db_models import Tenant, User
from app.services import auth_service


@pytest.fixture(scope="module", autouse=True)
def seed():
    init_db()
    db = SessionLocal()
    try:
        t1 = Tenant(name="DuPage Health Coalition", slug="dupage")
        t2 = Tenant(name="Other Org", slug="other")
        db.add_all([t1, t2]); db.commit(); db.refresh(t1); db.refresh(t2)
        db.add_all([
            User(tenant_id=t1.id, email="admin@dupage.org", full_name="Admin",
                 hashed_password=auth_service.hash_password("dupagepass"), role="admin"),
            User(tenant_id=t1.id, email="member@dupage.org",
                 hashed_password=auth_service.hash_password("memberpass"), role="member"),
            User(tenant_id=t2.id, email="admin@other.org",
                 hashed_password=auth_service.hash_password("otherpass"), role="admin"),
        ])
        db.commit()
        yield {"t1": t1.id, "t2": t2.id}
    finally:
        db.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return r


def _token(client, email, password):
    return _login(client, email, password).json()["access_token"]


def test_password_hash_roundtrip():
    h = auth_service.hash_password("s3cret!")
    assert auth_service.verify_password("s3cret!", h)
    assert not auth_service.verify_password("wrong", h)


def test_jwt_roundtrip():
    tok = auth_service.create_access_token(user_id=1, email="a@b.c", tenant_id=9, role="admin")
    payload = auth_service.decode_token(tok)
    assert payload["sub"] == "1" and payload["tenant_id"] == 9 and payload["role"] == "admin"
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
                    json={"email": "new@dupage.org", "password": "newpass123", "role": "member"})
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
