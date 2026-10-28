from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, serializers
from app.config import get_settings
from app.db import get_db
from app.deps import COOKIE_NAME, current_user
from app.errors import AppError
from app.models import Notification, User
from app.security import create_token, verify_password

router = APIRouter(prefix="/api", tags=["auth"])


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


@router.post("/auth/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        audit.record(db, "auth.login_failed", "User", user.id if user else None, actor_type="SYSTEM", org_id=user.org_id if user else None)
        db.commit()
        raise AppError("invalid_credentials", "Email or password is incorrect", 401)
    token = create_token(user.id, user.role.value, user.token_version)
    s = get_settings()
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", secure=s.cookie_secure, max_age=s.jwt_ttl_minutes * 60, path="/")
    audit.record(db, "auth.login", "User", user.id, actor=user)
    db.commit()
    return {"user": serializers.user(user), "token": token}


@router.get("/auth/me")
def me(user: User = Depends(current_user)) -> dict:
    return serializers.user(user)


@router.post("/auth/logout")
def logout(response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    user = db.merge(user)
    user.token_version += 1  # invalidates every token issued so far
    audit.record(db, "auth.logout", "User", user.id, actor=user)
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/notifications")
def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(50))
    return [serializers.notification(n) for n in rows]


@router.post("/notifications/read-all")
def read_all(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    from app.services import now

    for n in db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))):
        n.read_at = now()
    db.commit()
    return {"ok": True}
