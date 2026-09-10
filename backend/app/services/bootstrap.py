"""Startup bootstrap: optionally create tenant + users from environment variables.

Makes deployment declarative — set a couple of secrets and the accounts exist on
every environment (here and United Way), with no shelling into the container.
All operations are idempotent and NEVER overwrite an existing user's password.

Env:
  SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD [+ SEED_ADMIN_NAME]   -> one admin
  SEED_TENANT_NAME (default "DuPage Health Coalition") / SEED_TENANT_SLUG (default "dupage")
  SEED_USERS = JSON list, e.g.
     [{"email":"jane@dupagehealth.org","password":"...","name":"Jane Doe","role":"user"}]
     -> additional named users in the same tenant (great for pilot testers)
"""
import json
import os
from typing import List, Optional, Tuple

from app.db import SessionLocal
from app.models.core_models import Tenant, User
from app.services import auth_service


def _tenant_defaults() -> Tuple[str, str]:
    return (os.getenv("SEED_TENANT_NAME", "DuPage Health Coalition"),
            os.getenv("SEED_TENANT_SLUG", "dupage"))


def ensure_user(*, tenant_name: str, slug: str, email: str, password: str,
                role: str = "user", full_name: Optional[str] = None) -> str:
    """Create tenant (if missing) and a user (if missing). Returns 'created' | 'exists'."""
    email = email.strip().lower()
    # Accept the legacy spelling from a SEED_USERS value already deployed.
    if role == "member":
        role = "user"
    role = role if role in ("admin", "user") else "user"
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
        if not tenant:
            tenant = Tenant(name=tenant_name, slug=slug)
            db.add(tenant); db.commit(); db.refresh(tenant)
        if db.query(User).filter(User.email == email).first():
            return "exists"
        db.add(User(
            tenant_id=tenant.id, email=email, full_name=full_name,
            hashed_password=auth_service.hash_password(password),
            role=role, is_active=True,
        ))
        db.commit()
        return "created"
    finally:
        db.close()


def ensure_admin(*, tenant_name: str, slug: str, email: str, password: str,
                 full_name: Optional[str] = None) -> str:
    return ensure_user(tenant_name=tenant_name, slug=slug, email=email,
                       password=password, role="admin", full_name=full_name)


def seed_from_env() -> Optional[str]:
    """Ensure the admin from SEED_ADMIN_* exists. No-op when unset."""
    email = os.getenv("SEED_ADMIN_EMAIL")
    password = os.getenv("SEED_ADMIN_PASSWORD")
    if not email or not password:
        return None
    name, slug = _tenant_defaults()
    return ensure_admin(tenant_name=name, slug=slug, email=email,
                        password=password, full_name=os.getenv("SEED_ADMIN_NAME"))


def seed_users_from_env() -> List[Tuple[str, str]]:
    """Ensure each user in the SEED_USERS JSON list exists. Returns [(email, status)]."""
    raw = os.getenv("SEED_USERS")
    if not raw:
        return []
    try:
        users = json.loads(raw)
        if not isinstance(users, list):
            return []
    except (json.JSONDecodeError, TypeError):
        return []
    tenant_name, slug = _tenant_defaults()
    results: List[Tuple[str, str]] = []
    for u in users:
        if not isinstance(u, dict):
            continue
        email, password = u.get("email"), u.get("password")
        if not email or not password:
            continue
        status = ensure_user(
            tenant_name=tenant_name, slug=slug, email=email, password=password,
            role=u.get("role", "user"), full_name=u.get("name"),
        )
        results.append((email.strip().lower(), status))
    return results
