"""Authentication endpoints — email + password login, JWT sessions, and
admin-guarded user management scoped to the caller's tenant."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from sqlalchemy import text

from app import tenancy
from app.db import SessionLocal, get_db
from app.deps import get_current_user, require_admin
from app.models.auth_schemas import LoginRequest, TokenResponse, UserCreate, UserOut
from app.models.core_models import User
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


# One message for every way logging in can fail. Distinguishing "no such
# organization" from "no such user" from "wrong password" would let anyone
# enumerate which nonprofits are on the platform and who works there.
_LOGIN_FAILED = "Incorrect organization, email or password"


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Organization first, then the person.

    A database session cannot be scoped until we know which organization is
    being logged into, and under row-level security an unscoped lookup of
    core.users returns nothing. So the slug is resolved first, against
    core.tenant_directory — the one deliberately global view, two columns
    wide — and the user lookup then happens inside that organization's
    scope, like every other query in the application.

    Two sessions on purpose. The first is marked unscoped to read the
    directory, and a session that has already run an unscoped statement
    cannot be retrospectively scoped, so the user lookup gets its own.
    """
    slug = body.organization.strip().lower()

    tenancy.mark_session_unscoped(
        db, "login: resolving the organization before a tenant is known")
    row = db.execute(
        text("SELECT id FROM core.tenant_directory WHERE lower(slug) = :s"),
        {"s": slug},
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=_LOGIN_FAILED)
    tenant_id = str(row[0])

    scoped = SessionLocal()
    try:
        tenancy.bind_session_to_tenant(scoped, tenant_id)
        user = scoped.query(User).filter(User.email == body.email.lower()).first()
        if not user or not auth_service.verify_password(body.password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail=_LOGIN_FAILED)
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Account is disabled")
        token = auth_service.create_access_token(
            user_id=user.id, email=user.email, tenant_id=user.tenant_id, role=user.role,
        )
        return TokenResponse(access_token=token, user=UserOut.model_validate(user))
    finally:
        scoped.close()


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Admins invite new users into their own tenant."""
    email = body.email.lower()
    exists = db.query(User).filter(User.tenant_id == admin.tenant_id, User.email == email).first()
    if exists:
        raise HTTPException(status_code=409, detail="A user with that email already exists")
    user = User(
        tenant_id=admin.tenant_id,
        email=email,
        full_name=body.full_name,
        hashed_password=auth_service.hash_password(body.password),
        role=body.role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.get("/users", response_model=list[UserOut])
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [UserOut.model_validate(u) for u in
            db.query(User).filter(User.tenant_id == admin.tenant_id).all()]
