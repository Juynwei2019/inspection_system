"""登入、登出、目前使用者與密碼修改。"""
import os
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field
from fastapi import APIRouter, Cookie, Depends, Response
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..auth import (COOKIE_NAME, SESSION_SECONDS, add_audit, create_session, get_current_user,
                    hash_password, revoke_user_sessions, token_hash, user_data, verify_password)
from ..common import fail, utc_now
from ..db import get_session
from ..models import User, UserSession

router = APIRouter(prefix="/api/v1/auth", tags=["登入"])


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class PasswordChangeInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


def set_session_cookie(response: Response, token: str):
    response.set_cookie(
        COOKIE_NAME, token, max_age=SESSION_SECONDS,
        httponly=True, samesite="lax",
        secure=os.getenv("INSPECTION_COOKIE_SECURE", "false").lower() == "true", path="/",
    )


@router.post("/login")
def login(payload: LoginInput, response: Response, session: Session = Depends(get_session)):
    username = payload.username.strip().lower()
    user = session.scalar(select(User).where(func.lower(User.username) == username))
    now = datetime.now(timezone.utc)
    if user and user.locked_until:
        locked_until = datetime.fromisoformat(user.locked_until.replace("Z", "+00:00"))
        if locked_until > now:
            add_audit(session, user, "login_locked", "user", user.id, "帳號暫時鎖定")
            session.commit()
            fail(423, "account_locked", "登入失敗次數過多，請稍後再試")
        user.locked_until = None
        user.failed_login_count = 0
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        if user and user.is_active:
            user.failed_login_count += 1
            if user.failed_login_count >= 5:
                user.locked_until = (now + timedelta(minutes=15)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            add_audit(session, user, "login_failed", "user", user.id, "帳號或密碼錯誤")
        else:
            add_audit(session, None, "login_failed", "user", None, "不存在或已停用的帳號", username=username)
        session.commit()
        fail(401, "invalid_credentials", "帳號或密碼不正確")
    user.last_login_at = utc_now()
    user.failed_login_count = 0
    user.locked_until = None
    token = create_session(session, user)
    add_audit(session, user, "login_success", "user", user.id, "登入成功")
    session.commit()
    set_session_cookie(response, token)
    return {"user": user_data(user)}


@router.post("/logout", status_code=204)
def logout(response: Response, session: Session = Depends(get_session),
           token: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    if token:
        login_session = session.scalar(select(UserSession).where(UserSession.token_hash == token_hash(token)))
        if login_session and login_session.revoked_at is None:
            login_session.revoked_at = utc_now()
            user = session.get(User, login_session.user_id)
            add_audit(session, user, "logout", "user", login_session.user_id, "登出")
            session.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"user": user_data(user)}


@router.post("/change-password")
def change_password(payload: PasswordChangeInput, response: Response,
                    user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    if not verify_password(payload.current_password, user.password_hash):
        fail(422, "incorrect_current_password", "目前密碼不正確")
    if payload.current_password == payload.new_password:
        fail(422, "password_unchanged", "新密碼不可與目前密碼相同")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.session_version += 1
    user.updated_at = utc_now()
    revoke_user_sessions(session, user.id)
    token = create_session(session, user)
    add_audit(session, user, "password_changed", "user", user.id, "使用者修改密碼")
    session.commit()
    session.refresh(user)
    set_session_cookie(response, token)
    return {"user": user_data(user)}
