"""密碼雜湊、簽章登入 Cookie 與身分驗證相依項。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .common import fail, new_id, utc_now
from .db import get_session
from .models import AuditLog, User, UserSession

COOKIE_NAME = "inspection_session"
SESSION_SECONDS = int(os.getenv("INSPECTION_SESSION_SECONDS", "28800"))
PBKDF2_ITERATIONS = 310_000
ROLE_LABELS = {
    "system_admin": "系統管理員",
    "inspection_manager": "巡檢管理員",
    "inspector": "巡檢人員",
    "viewer": "查詢人員",
}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode().rstrip("="),
        base64.urlsafe_b64encode(digest).decode().rstrip("="),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_text, expected_text = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = _decode(salt_text)
        expected = _decode(expected_text)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(session: Session, user: User) -> str:
    token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    session.add(UserSession(
        id=new_id(), user_id=user.id, token_hash=token_hash(token), created_at=utc_now(),
        expires_at=(now + timedelta(seconds=SESSION_SECONDS)).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        last_seen_at=utc_now(), revoked_at=None,
    ))
    return token


def revoke_user_sessions(session: Session, user_id: str) -> None:
    session.execute(update(UserSession).where(
        UserSession.user_id == user_id, UserSession.revoked_at.is_(None),
    ).values(revoked_at=utc_now()))


def add_audit(session: Session, user: User | None, action: str, target_type: str = "",
              target_id: str | None = None, summary: str = "", username: str = "") -> None:
    session.add(AuditLog(
        id=new_id(), user_id=user.id if user else None,
        username_snapshot=user.username if user else username,
        action=action, target_type=target_type, target_id=target_id,
        summary=summary, created_at=utc_now(),
    ))


def current_user_optional(
    session: Session = Depends(get_session),
    token: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> User | None:
    if not token:
        return None
    login_session = session.scalar(select(UserSession).where(
        UserSession.token_hash == token_hash(token), UserSession.revoked_at.is_(None),
        UserSession.expires_at > utc_now(),
    ))
    if not login_session:
        return None
    user = session.get(User, login_session.user_id)
    if not user or not user.is_active:
        return None
    return user


def get_current_user(user: User | None = Depends(current_user_optional)) -> User:
    if user is None:
        fail(401, "authentication_required", "請先登入")
    return user


def require_roles(*allowed: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.must_change_password:
            fail(403, "password_change_required", "請先修改臨時密碼")
        if user.role not in allowed:
            fail(403, "permission_denied", "你沒有權限使用此功能")
        return user
    return dependency


require_system_admin = require_roles("system_admin")
require_maintenance = require_roles("system_admin", "inspection_manager")
require_inspection = require_roles("system_admin", "inspection_manager", "inspector")
require_results = require_roles("system_admin", "inspection_manager", "inspector", "viewer")


def require_password_changed(user: User = Depends(get_current_user)) -> User:
    if user.must_change_password:
        fail(403, "password_change_required", "請先修改臨時密碼")
    return user


def user_data(user: User) -> dict:
    return {"id": user.id, "username": user.username, "display_name": user.display_name,
            "role": user.role, "role_label": ROLE_LABELS.get(user.role, user.role),
            "department": user.department, "email": user.email,
            "is_active": user.is_active, "must_change_password": user.must_change_password,
            "last_login_at": user.last_login_at, "created_at": user.created_at}
