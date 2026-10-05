"""系統管理員使用的帳號與操作紀錄管理。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import add_audit, hash_password, require_system_admin, revoke_user_sessions, user_data
from ..common import fail, new_id, utc_now
from ..db import get_session
from ..models import AuditLog, User
from ..schemas import PasswordResetInput, UserCreate, UserUpdate

router = APIRouter(prefix="/api/v1", tags=["帳號與權限"])


def active_admin_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(User).where(
        User.role == "system_admin", User.is_active.is_(True),
    )) or 0


def get_user_or_404(session: Session, user_id: str) -> User:
    user = session.get(User, user_id)
    if not user:
        fail(404, "user_not_found", "使用者不存在")
    return user


@router.get("/users")
def list_users(query: str = Query(default="", max_length=100), role: str | None = None,
               active: bool | None = None, session: Session = Depends(get_session),
               _admin: User = Depends(require_system_admin)):
    stmt = select(User)
    if query.strip():
        q = f"%{query.strip()}%"
        stmt = stmt.where(User.username.ilike(q) | User.display_name.ilike(q) | User.department.ilike(q))
    if role:
        stmt = stmt.where(User.role == role)
    if active is not None:
        stmt = stmt.where(User.is_active.is_(active))
    users = session.scalars(stmt.order_by(User.is_active.desc(), User.username)).all()
    return {"items": [user_data(x) for x in users]}


@router.post("/users", status_code=201)
def create_user(payload: UserCreate, session: Session = Depends(get_session),
                admin: User = Depends(require_system_admin)):
    now = utc_now()
    user = User(
        id=new_id(), username=payload.username.strip().lower(), display_name=payload.display_name.strip(),
        department=payload.department.strip(), email=payload.email.strip(),
        password_hash=hash_password(payload.temporary_password), role=payload.role,
        is_active=payload.is_active, must_change_password=True, failed_login_count=0,
        locked_until=None, session_version=1, created_by=admin.id,
        created_at=now, updated_at=now, last_login_at=None,
    )
    if not user.display_name:
        fail(422, "invalid_display_name", "顯示姓名不可空白")
    session.add(user)
    add_audit(session, admin, "user_created", "user", user.id,
              f"建立帳號 {user.username}，角色 {user.role}")
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        fail(409, "username_exists", "登入帳號已存在")
    return user_data(user)


@router.patch("/users/{user_id}")
def update_user(user_id: str, payload: UserUpdate, session: Session = Depends(get_session),
                admin: User = Depends(require_system_admin)):
    user = get_user_or_404(session, user_id)
    changes = payload.model_dump(exclude_unset=True)
    if any(value is None for value in changes.values()):
        fail(422, "null_not_allowed", "欄位不可設為 null")
    if user.id == admin.id and changes.get("is_active") is False:
        fail(422, "cannot_deactivate_self", "不能停用自己的帳號")
    removing_last_admin = user.role == "system_admin" and user.is_active and (
        changes.get("role", user.role) != "system_admin" or changes.get("is_active", True) is False
    )
    if removing_last_admin and active_admin_count(session) <= 1:
        fail(422, "last_admin_required", "系統至少要保留一位有效的系統管理員")
    if "display_name" in changes:
        changes["display_name"] = changes["display_name"].strip()
        if not changes["display_name"]:
            fail(422, "invalid_display_name", "顯示姓名不可空白")
    for key in ("department", "email"):
        if key in changes:
            changes[key] = changes[key].strip()
    security_change = any(key in changes for key in ("role", "is_active"))
    for key, value in changes.items():
        setattr(user, key, value)
    user.updated_at = utc_now()
    if security_change:
        revoke_user_sessions(session, user.id)
    add_audit(session, admin, "user_updated", "user", user.id,
              f"更新帳號 {user.username}：{', '.join(changes) or '無變更'}")
    session.commit()
    return user_data(user)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: str, payload: PasswordResetInput, session: Session = Depends(get_session),
                   admin: User = Depends(require_system_admin)):
    user = get_user_or_404(session, user_id)
    user.password_hash = hash_password(payload.temporary_password)
    user.must_change_password = True
    user.failed_login_count = 0
    user.locked_until = None
    user.updated_at = utc_now()
    revoke_user_sessions(session, user.id)
    add_audit(session, admin, "password_reset", "user", user.id, f"重設帳號 {user.username} 的密碼")
    session.commit()
    return {"user": user_data(user)}


@router.post("/users/{user_id}/revoke-sessions", status_code=204)
def revoke_sessions(user_id: str, session: Session = Depends(get_session),
                    admin: User = Depends(require_system_admin)):
    user = get_user_or_404(session, user_id)
    revoke_user_sessions(session, user.id)
    add_audit(session, admin, "sessions_revoked", "user", user.id, f"登出帳號 {user.username} 的所有裝置")
    session.commit()


@router.get("/audit-logs")
def list_audit_logs(limit: int = Query(default=100, ge=1, le=500),
                    session: Session = Depends(get_session),
                    _admin: User = Depends(require_system_admin)):
    rows = session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)).all()
    return {"items": [{"id": x.id, "username": x.username_snapshot, "action": x.action,
                        "target_type": x.target_type, "target_id": x.target_id,
                        "summary": x.summary, "created_at": x.created_at} for x in rows]}
