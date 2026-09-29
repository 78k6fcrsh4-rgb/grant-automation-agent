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

from sqlalchemy import text

from app import tenancy
from app.db import SessionLocal
from app.models.core_models import User
from app.services import auth_service


class OrganizationNotProvisioned(RuntimeError):
    """The organization does not exist and the app cannot create it.

    With several organizations in one database, creating one is an admin
    operation, not something an application role may do: core.tenants is
    protected by a policy comparing tenant_id against the session's
    organization, and a session that has no organization yet cannot satisfy
    it. That is the policy behaving correctly — a service that can mint
    organizations can also mint itself access to one.
    """


def _resolve_tenant_id(slug: str) -> Optional[str]:
    """Look the organization up in the one globally readable view."""
    db = SessionLocal()
    try:
        tenancy.mark_session_unscoped(
            db, "bootstrap: resolving the organization before a tenant is known")
        row = db.execute(
            text("SELECT id FROM core.tenant_directory WHERE lower(slug) = :s"),
            {"s": slug.strip().lower()},
        ).first()
        return str(row[0]) if row else None
    finally:
        db.close()


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
    tenant_id = _resolve_tenant_id(slug)
    if tenant_id is None:
        raise OrganizationNotProvisioned(
            f"No organization with slug '{slug}' exists, and the application "
            f"role cannot create one — adding an organization is an admin "
            f"operation now that several share a database. Create it with "
            f"admin credentials first:\n"
            f"    ./infra/add-organization.sh {slug} \"{tenant_name}\"\n"
            f"then restart so seeding can run."
        )

    db = SessionLocal()
    try:
        tenancy.bind_session_to_tenant(db, tenant_id)
        if db.query(User).filter(User.email == email).first():
            return "exists"
        db.add(User(
            tenant_id=tenant_id, email=email, full_name=full_name,
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
