"""Shared FastAPI dependencies for authentication/authorization."""
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app import tenancy
from app.db import get_db
from app.models.core_models import User
from app.services import auth_service

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    payload = auth_service.decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    try:
        user_id = uuid.UUID(str(payload.get("sub", "")))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    # The organization comes from the signed token, never from anything the
    # caller can set on the request. Binding happens before the first query,
    # so every statement in this request — here and in the route, which is
    # handed the same session — runs scoped.
    tenant_claim = str(payload.get("tenant_id", "")).strip()
    try:
        uuid.UUID(tenant_claim)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    tenancy.bind_session_to_tenant(db, tenant_claim)

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    # Belt and braces: the policies already make a mismatched user
    # unreadable, so reaching this line means something is wrong in a way
    # worth refusing rather than tolerating.
    if str(user.tenant_id) != tenant_claim:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return user
