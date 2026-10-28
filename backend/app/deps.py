import uuid
from collections.abc import Callable

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError, Forbidden
from app.models import User, UserRole
from app.security import decode_token

COOKIE_NAME = "mh_session"


class Unauthorized(AppError):
    status_code = 401

    def __init__(self) -> None:
        super().__init__("unauthorized", "Authentication required")


def _token_from_request(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(COOKIE_NAME)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _token_from_request(request)
    if not token:
        raise Unauthorized()
    try:
        payload = decode_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise Unauthorized()
    user = db.scalar(select(User).where(User.id == user_id))
    if not user or not user.is_active or payload.get("tv") != user.token_version:
        raise Unauthorized()
    return user


def require_role(*roles: UserRole) -> Callable[[User], User]:
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise Forbidden()
        return user

    return dep


patient_user = require_role(UserRole.PATIENT)
clinician_user = require_role(UserRole.CLINICIAN)
admin_user = require_role(UserRole.ADMIN)
