"""Startup bootstrap: optionally create the first tenant + admin from env vars.

This makes deployment a two-secret affair (SEED_ADMIN_EMAIL, SEED_ADMIN_PASSWORD)
instead of shelling into the running container to seed. Idempotent and safe:
it only creates the admin if that email doesn't already exist, and it NEVER
overwrites an existing user's password.
"""
import os
from typing import Optional

from app.db import SessionLocal
from app.models.db_models import Tenant, User
from app.services import auth_service


def ensure_admin(*, tenant_name: str, slug: str, email: str, password: str,
                 full_name: Optional[str] = None) -> str:
    """Create tenant (if missing) and an admin user (if missing). Returns a status."""
    email = email.strip().lower()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
        if not tenant:
            tenant = Tenant(name=tenant_name, slug=slug)
            db.add(tenant); db.commit(); db.refresh(tenant)
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            return "exists"
        db.add(User(
            tenant_id=tenant.id, email=email, full_name=full_name,
            hashed_password=auth_service.hash_password(password),
            role="admin", is_active=True,
        ))
        db.commit()
        return "created"
    finally:
        db.close()


def seed_from_env() -> Optional[str]:
    """If SEED_ADMIN_EMAIL and SEED_ADMIN_PASSWORD are set, ensure that admin
    exists. No-op when they're unset. Returns 'created' | 'exists' | None."""
    email = os.getenv("SEED_ADMIN_EMAIL")
    password = os.getenv("SEED_ADMIN_PASSWORD")
    if not email or not password:
        return None
    return ensure_admin(
        tenant_name=os.getenv("SEED_TENANT_NAME", "DuPage Health Coalition"),
        slug=os.getenv("SEED_TENANT_SLUG", "dupage"),
        email=email,
        password=password,
        full_name=os.getenv("SEED_ADMIN_NAME"),
    )
