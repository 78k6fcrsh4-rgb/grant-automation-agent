"""Authentication endpoints — email + password login, JWT sessions, and
admin-guarded user management scoped to the caller's tenant."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_admin
from app.models.auth_schemas import LoginRequest, TokenResponse, UserCreate, UserOut
from app.models.core_models import User
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    # Email is unique per tenant; for single-org login we match on email only.
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or not auth_service.verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
    token = auth_service.create_access_token(
        user_id=user.id, email=user.email, tenant_id=user.tenant_id, role=user.role,
    )
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


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
