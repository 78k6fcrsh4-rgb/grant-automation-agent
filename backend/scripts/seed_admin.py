"""Create the first tenant + admin user. Run once after deploy.

Usage:
  python -m scripts.seed_admin --tenant "DuPage Health Coalition" --slug dupage \
      --email admin@dupagehealth.org --password 'STRONGPASSWORD' --name "Kara Murphy"

Idempotent: re-running with the same slug/email updates the password.
"""
import argparse
from app.db import SessionLocal, init_db
from app.models.db_models import Tenant, User
from app.services import auth_service


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tenant", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--name", default=None)
    p.add_argument("--role", default="admin", choices=["admin", "member"])
    args = p.parse_args()

    init_db()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.slug == args.slug).first()
        if not tenant:
            tenant = Tenant(name=args.tenant, slug=args.slug)
            db.add(tenant); db.commit(); db.refresh(tenant)
            print(f"created tenant {tenant.name!r} (id={tenant.id})")
        else:
            print(f"tenant {tenant.name!r} already exists (id={tenant.id})")

        email = args.email.lower()
        user = db.query(User).filter(User.tenant_id == tenant.id, User.email == email).first()
        if not user:
            user = User(tenant_id=tenant.id, email=email, full_name=args.name,
                        hashed_password=auth_service.hash_password(args.password),
                        role=args.role, is_active=True)
            db.add(user); db.commit()
            print(f"created {args.role} user {email}")
        else:
            user.hashed_password = auth_service.hash_password(args.password)
            user.role = args.role
            db.commit()
            print(f"updated password/role for existing user {email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
