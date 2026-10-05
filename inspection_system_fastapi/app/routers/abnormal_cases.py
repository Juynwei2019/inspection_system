"""異常案件：指派、改善、複查、歷程與照片。"""
from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import case as sql_case, func, or_, select, update
from sqlalchemy.orm import Session

from ..auth import add_audit, require_results
from ..common import attachment_data, fail, new_id, utc_now
from ..db import PROJECT_ROOT, get_session
from ..models import (
    AbnormalCase, AbnormalCaseAttachment, AbnormalCaseHistory, Inspection,
    InspectionResult, InspectionResultAttachment, User,
)
from ..schemas import AbnormalActionInput, AbnormalAssignmentInput, AbnormalCorrectionInput

router = APIRouter(prefix="/api/v1/abnormal-cases", tags=["異常追蹤"])
UPLOAD_DIR = Path(os.getenv("INSPECTION_UPLOAD_DIR", str(PROJECT_ROOT / "data" / "uploads"))).resolve()
MAX_FILE_BYTES = int(os.getenv("INSPECTION_PHOTO_MAX_BYTES", str(5 * 1024 * 1024)))
MAX_PHOTOS_PER_STAGE = int(os.getenv("ABNORMAL_PHOTO_MAX_COUNT", "5"))
MIME_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MANAGER_ROLES = {"system_admin", "inspection_manager"}
OPEN_STATUSES = {"pending", "in_progress", "pending_review"}
TAIPEI = ZoneInfo("Asia/Taipei")


def _today() -> str:
    return datetime.now(TAIPEI).date().isoformat()


def _detected_mime(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _manager(user: User) -> bool:
    return user.role in MANAGER_ROLES


def _viewable(record: AbnormalCase, inspection: Inspection, user: User) -> bool:
    return user.role != "inspector" or inspection.inspector_user_id == user.id or record.assignee_user_id == user.id


def _require_view(record: AbnormalCase, inspection: Inspection, user: User) -> None:
    if not _viewable(record, inspection, user):
        fail(403, "permission_denied", "你只能查看自己提報或負責的異常案件")


def _get_case(session: Session, case_id: str):
    row = session.execute(
        select(AbnormalCase, Inspection, InspectionResult)
        .join(Inspection, Inspection.id == AbnormalCase.inspection_id)
        .join(InspectionResult, InspectionResult.id == AbnormalCase.inspection_result_id)
        .where(AbnormalCase.id == case_id)
    ).first()
    if not row:
        fail(404, "abnormal_case_not_found", "異常案件不存在")
    return row


def _attachment_data(x: AbnormalCaseAttachment) -> dict:
    return {
        "id": x.id, "stage": x.stage, "original_name": x.original_name,
        "mime_type": x.mime_type, "file_size": x.file_size, "created_at": x.created_at,
        "content_url": f"/api/v1/abnormal-cases/attachments/{x.id}/content",
    }


def _history_data(x: AbnormalCaseHistory) -> dict:
    return {
        "id": x.id, "actor_name": x.actor_name_snapshot, "action": x.action,
        "from_status": x.from_status, "to_status": x.to_status,
        "note": x.note, "created_at": x.created_at,
    }


def _case_data(session: Session, record: AbnormalCase, inspection: Inspection,
               result: InspectionResult, detail: bool = False) -> dict:
    today = _today()
    data = {
        "id": record.id, "case_number": record.case_number,
        "inspection_id": record.inspection_id, "inspection_number": inspection.number,
        "inspection_result_id": record.inspection_result_id,
        "location_name": inspection.location_name_snapshot, "location_code": inspection.location_code_snapshot,
        "area": inspection.area_snapshot, "inspector": inspection.inspector_name_snapshot or inspection.inspector,
        "item_code": result.item_code_snapshot, "item_name": result.item_name_snapshot,
        "category": result.category_snapshot, "title": record.title,
        "description": record.description, "severity": record.severity, "status": record.status,
        "assignee_user_id": record.assignee_user_id, "assignee_name": record.assignee_name_snapshot,
        "due_date": record.due_date, "corrective_action": record.corrective_action,
        "review_note": record.review_note, "created_by": record.created_by,
        "created_at": record.created_at, "updated_at": record.updated_at,
        "closed_at": record.closed_at, "version": record.version,
        "is_overdue": bool(record.due_date and record.due_date < today and record.status in OPEN_STATUSES),
    }
    if detail:
        original = list(session.scalars(select(InspectionResultAttachment).where(
            InspectionResultAttachment.inspection_result_id == result.id
        ).order_by(InspectionResultAttachment.created_at)))
        attachments = list(session.scalars(select(AbnormalCaseAttachment).where(
            AbnormalCaseAttachment.case_id == record.id
        ).order_by(AbnormalCaseAttachment.created_at)))
        history = list(session.scalars(select(AbnormalCaseHistory).where(
            AbnormalCaseHistory.case_id == record.id
        ).order_by(AbnormalCaseHistory.created_at, AbnormalCaseHistory.id)))
        data["inspection_photos"] = [attachment_data(x) for x in original]
        data["attachments"] = [_attachment_data(x) for x in attachments]
        data["history"] = [_history_data(x) for x in history]
    return data


def _add_history(session: Session, record: AbnormalCase, user: User, action: str,
                 from_status: str | None = None, to_status: str | None = None, note: str = "") -> None:
    session.add(AbnormalCaseHistory(
        id=new_id(), case_id=record.id, actor_user_id=user.id,
        actor_name_snapshot=user.display_name, action=action,
        from_status=from_status, to_status=to_status, note=note.strip(), created_at=utc_now(),
    ))


def _transition(session: Session, record: AbnormalCase, user: User, payload: AbnormalActionInput,
                expected: str, target: str, action: str, note_required: bool = False,
                extra: dict | None = None):
    if record.status != expected:
        fail(409, "invalid_case_status", "案件目前狀態不允許此操作")
    if record.version != payload.version:
        fail(409, "case_conflict", "案件已有較新的修改，請重新讀取")
    note = payload.note.strip()
    if note_required and not note:
        fail(422, "note_required", "請填寫處理說明")
    values = {"status": target, "updated_at": utc_now(), "version": payload.version + 1, **(extra or {})}
    changed = session.execute(update(AbnormalCase).where(
        AbnormalCase.id == record.id, AbnormalCase.status == expected,
        AbnormalCase.version == payload.version,
    ).values(**values))
    if changed.rowcount != 1:
        session.rollback()
        fail(409, "case_conflict", "案件已有較新的修改，請重新讀取")
    _add_history(session, record, user, action, expected, target, note)
    add_audit(session, user, f"abnormal_case_{action}", "abnormal_case", record.id,
              f"{record.case_number}：{note or action}")
    session.commit()


@router.get("/assignees")
def list_assignees(session: Session = Depends(get_session), user: User = Depends(require_results)):
    if not _manager(user):
        fail(403, "permission_denied", "只有管理員可指派異常案件")
    rows = session.scalars(select(User).where(
        User.is_active.is_(True), User.role.in_(["system_admin", "inspection_manager", "inspector"])
    ).order_by(User.display_name, User.username)).all()
    return {"items": [{"id": x.id, "display_name": x.display_name,
                       "username": x.username, "department": x.department} for x in rows]}


@router.get("")
def list_cases(
    status: str | None = Query(default=None, pattern=r"^(pending|in_progress|pending_review|closed|cancelled)$"),
    severity: str | None = Query(default=None, pattern=r"^(minor|normal|major)$"),
    overdue: bool | None = None, assignee_user_id: str | None = None,
    query: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session), user: User = Depends(require_results),
):
    stmt = (select(AbnormalCase, Inspection, InspectionResult)
            .join(Inspection, Inspection.id == AbnormalCase.inspection_id)
            .join(InspectionResult, InspectionResult.id == AbnormalCase.inspection_result_id))
    if user.role == "inspector":
        stmt = stmt.where(or_(Inspection.inspector_user_id == user.id, AbnormalCase.assignee_user_id == user.id))
    if status:
        stmt = stmt.where(AbnormalCase.status == status)
    if severity:
        stmt = stmt.where(AbnormalCase.severity == severity)
    if assignee_user_id:
        stmt = stmt.where(AbnormalCase.assignee_user_id == assignee_user_id)
    if overdue is not None:
        overdue_expr = AbnormalCase.due_date < _today()
        open_expr = AbnormalCase.status.in_(list(OPEN_STATUSES))
        stmt = stmt.where(overdue_expr & open_expr if overdue else ~(overdue_expr & open_expr))
    if query.strip():
        q = f"%{query.strip()}%"
        stmt = stmt.where(or_(
            AbnormalCase.case_number.ilike(q), AbnormalCase.title.ilike(q),
            Inspection.location_name_snapshot.ilike(q), InspectionResult.item_name_snapshot.ilike(q),
            AbnormalCase.assignee_name_snapshot.ilike(q),
        ))
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = session.execute(stmt.order_by(
        sql_case((AbnormalCase.status.in_(list(OPEN_STATUSES)), 0), else_=1),
        AbnormalCase.due_date.asc(), AbnormalCase.created_at.desc(),
    ).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_case_data(session, *row) for row in rows], "total": total,
            "page": page, "page_size": page_size}


@router.get("/summary")
def case_summary(session: Session = Depends(get_session), user: User = Depends(require_results)):
    base = (select(AbnormalCase.status, AbnormalCase.due_date)
            .join(Inspection, Inspection.id == AbnormalCase.inspection_id))
    if user.role == "inspector":
        base = base.where(or_(Inspection.inspector_user_id == user.id, AbnormalCase.assignee_user_id == user.id))
    rows = session.execute(base).all()
    today = _today()
    counts = defaultdict(int)
    for status, due_date in rows:
        counts[status] += 1
        if due_date and due_date < today and status in OPEN_STATUSES:
            counts["overdue"] += 1
    return {"pending": counts["pending"], "in_progress": counts["in_progress"],
            "pending_review": counts["pending_review"], "closed": counts["closed"],
            "overdue": counts["overdue"]}


@router.get("/{case_id}")
def get_case(case_id: str, session: Session = Depends(get_session), user: User = Depends(require_results)):
    record, inspection, result = _get_case(session, case_id)
    _require_view(record, inspection, user)
    return _case_data(session, record, inspection, result, True)


@router.patch("/{case_id}/assignment")
def assign_case(case_id: str, payload: AbnormalAssignmentInput,
                session: Session = Depends(get_session), user: User = Depends(require_results)):
    if not _manager(user):
        fail(403, "permission_denied", "只有管理員可指派異常案件")
    record, _inspection, _result = _get_case(session, case_id)
    if record.status not in OPEN_STATUSES:
        fail(409, "case_readonly", "已結案或取消的案件不可再修改")
    if record.version != payload.version:
        fail(409, "case_conflict", "案件已有較新的修改，請重新讀取")
    assignee = session.get(User, payload.assignee_user_id)
    if not assignee or not assignee.is_active or assignee.role == "viewer":
        fail(422, "invalid_assignee", "負責人不存在、已停用或不具處理權限")
    try:
        date.fromisoformat(payload.due_date)
    except ValueError:
        fail(422, "invalid_due_date", "預計完成日格式錯誤")
    changed = session.execute(update(AbnormalCase).where(
        AbnormalCase.id == record.id, AbnormalCase.version == payload.version,
        AbnormalCase.status.in_(list(OPEN_STATUSES)),
    ).values(assignee_user_id=assignee.id, assignee_name_snapshot=assignee.display_name,
             due_date=payload.due_date, severity=payload.severity,
             updated_at=utc_now(), version=payload.version + 1))
    if changed.rowcount != 1:
        session.rollback()
        fail(409, "case_conflict", "案件已有較新的修改，請重新讀取")
    _add_history(session, record, user, "assigned", record.status, record.status,
                 f"指派給 {assignee.display_name}，期限 {payload.due_date}")
    add_audit(session, user, "abnormal_case_assigned", "abnormal_case", record.id,
              f"{record.case_number} 指派給 {assignee.display_name}")
    session.commit()
    record, inspection, result = _get_case(session, case_id)
    return _case_data(session, record, inspection, result, True)


@router.post("/{case_id}/start")
def start_case(case_id: str, payload: AbnormalActionInput,
               session: Session = Depends(get_session), user: User = Depends(require_results)):
    record, inspection, _result = _get_case(session, case_id)
    _require_view(record, inspection, user)
    if not _manager(user) and record.assignee_user_id != user.id:
        fail(403, "permission_denied", "只有案件負責人可開始處理")
    if not record.assignee_user_id or not record.due_date:
        fail(422, "assignment_required", "請先設定負責人及預計完成日")
    _transition(session, record, user, payload, "pending", "in_progress", "started")
    record, inspection, result = _get_case(session, case_id)
    return _case_data(session, record, inspection, result, True)


@router.post("/{case_id}/submit-review")
def submit_review(case_id: str, payload: AbnormalCorrectionInput,
                  session: Session = Depends(get_session), user: User = Depends(require_results)):
    record, inspection, _result = _get_case(session, case_id)
    _require_view(record, inspection, user)
    if not _manager(user) and record.assignee_user_id != user.id:
        fail(403, "permission_denied", "只有案件負責人可送出複查")
    if record.status != "in_progress":
        fail(409, "invalid_case_status", "只有處理中的案件可送出複查")
    if record.version != payload.version:
        fail(409, "case_conflict", "案件已有較新的修改，請重新讀取")
    if record.severity == "major":
        photo_count = session.scalar(select(func.count()).select_from(AbnormalCaseAttachment).where(
            AbnormalCaseAttachment.case_id == record.id,
            AbnormalCaseAttachment.stage == "correction",
        )) or 0
        if not photo_count:
            fail(422, "correction_photo_required", "重大異常送出複查前至少需要一張改善照片")
    changed = session.execute(update(AbnormalCase).where(
        AbnormalCase.id == record.id, AbnormalCase.status == "in_progress",
        AbnormalCase.version == payload.version,
    ).values(status="pending_review", corrective_action=payload.corrective_action.strip(),
             updated_at=utc_now(), version=payload.version + 1))
    if changed.rowcount != 1:
        session.rollback()
        fail(409, "case_conflict", "案件已有較新的修改，請重新讀取")
    _add_history(session, record, user, "review_submitted", "in_progress", "pending_review",
                 payload.corrective_action)
    add_audit(session, user, "abnormal_case_review_submitted", "abnormal_case", record.id,
              f"{record.case_number} 已送出複查")
    session.commit()
    record, inspection, result = _get_case(session, case_id)
    return _case_data(session, record, inspection, result, True)


@router.post("/{case_id}/approve")
def approve_case(case_id: str, payload: AbnormalActionInput,
                 session: Session = Depends(get_session), user: User = Depends(require_results)):
    if not _manager(user):
        fail(403, "permission_denied", "只有管理員可複查結案")
    record, _inspection, _result = _get_case(session, case_id)
    if record.created_by == user.id:
        fail(422, "self_approval_not_allowed", "提報人不可自行複查結案")
    now = utc_now()
    _transition(session, record, user, payload, "pending_review", "closed", "approved",
                extra={"review_note": payload.note.strip(), "closed_by": user.id, "closed_at": now})
    record, inspection, result = _get_case(session, case_id)
    return _case_data(session, record, inspection, result, True)


@router.post("/{case_id}/reject")
def reject_case(case_id: str, payload: AbnormalActionInput,
                session: Session = Depends(get_session), user: User = Depends(require_results)):
    if not _manager(user):
        fail(403, "permission_denied", "只有管理員可退回改善")
    record, _inspection, _result = _get_case(session, case_id)
    _transition(session, record, user, payload, "pending_review", "in_progress", "rejected",
                note_required=True, extra={"review_note": payload.note.strip()})
    record, inspection, result = _get_case(session, case_id)
    return _case_data(session, record, inspection, result, True)


@router.post("/{case_id}/cancel")
def cancel_case(case_id: str, payload: AbnormalActionInput,
                session: Session = Depends(get_session), user: User = Depends(require_results)):
    if not _manager(user):
        fail(403, "permission_denied", "只有管理員可取消案件")
    record, _inspection, _result = _get_case(session, case_id)
    if record.status not in OPEN_STATUSES:
        fail(409, "invalid_case_status", "案件目前狀態不允許取消")
    _transition(session, record, user, payload, record.status, "cancelled", "cancelled", note_required=True)
    record, inspection, result = _get_case(session, case_id)
    return _case_data(session, record, inspection, result, True)


@router.post("/{case_id}/attachments", status_code=201)
async def upload_case_attachment(
    case_id: str, stage: str = Query(pattern=r"^(correction|review)$"), photo: UploadFile = File(...),
    session: Session = Depends(get_session), user: User = Depends(require_results),
):
    record, inspection, _result = _get_case(session, case_id)
    _require_view(record, inspection, user)
    if record.status in {"closed", "cancelled"}:
        fail(409, "case_readonly", "已結案或取消的案件照片不可變更")
    if stage == "correction":
        if record.status != "in_progress":
            fail(409, "invalid_case_status", "改善照片只能在處理中新增")
        if not _manager(user) and record.assignee_user_id != user.id:
            fail(403, "permission_denied", "只有案件負責人可新增改善照片")
    elif not _manager(user) or record.status != "pending_review":
        fail(403, "permission_denied", "複查照片只能由管理員於待複查時新增")
    count = session.scalar(select(func.count()).select_from(AbnormalCaseAttachment).where(
        AbnormalCaseAttachment.case_id == record.id, AbnormalCaseAttachment.stage == stage,
    )) or 0
    if count >= MAX_PHOTOS_PER_STAGE:
        fail(422, "photo_limit_reached", f"每個階段最多 {MAX_PHOTOS_PER_STAGE} 張照片")
    data = await photo.read(MAX_FILE_BYTES + 1)
    await photo.close()
    if not data:
        fail(422, "empty_photo", "照片檔案是空的")
    if len(data) > MAX_FILE_BYTES:
        fail(413, "photo_too_large", f"單張照片不可超過 {MAX_FILE_BYTES // (1024 * 1024)} MB")
    mime_type = _detected_mime(data)
    if mime_type is None:
        fail(415, "unsupported_photo_type", "僅支援 JPEG、PNG 或 WebP 圖片")
    attachment_id = new_id()
    stored_name = attachment_id.replace("-", "") + MIME_EXTENSIONS[mime_type]
    original_name = Path(photo.filename or "photo").name[:255] or "photo"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / stored_name
    temporary = UPLOAD_DIR / f".{stored_name}.tmp"
    temporary.write_bytes(data)
    temporary.replace(target)
    attachment = AbnormalCaseAttachment(
        id=attachment_id, case_id=record.id, stage=stage, original_name=original_name,
        stored_name=stored_name, mime_type=mime_type, file_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(), uploaded_by=user.id, created_at=utc_now(),
    )
    session.add(attachment)
    _add_history(session, record, user, f"{stage}_photo_uploaded", record.status, record.status,
                 f"新增照片 {original_name}")
    add_audit(session, user, "abnormal_case_photo_uploaded", "abnormal_case", record.id,
              f"{record.case_number} 新增{stage}照片")
    try:
        session.commit()
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return _attachment_data(attachment)


@router.get("/attachments/{attachment_id}/content")
def case_attachment_content(attachment_id: str, session: Session = Depends(get_session),
                            user: User = Depends(require_results)):
    row = session.execute(
        select(AbnormalCaseAttachment, AbnormalCase, Inspection)
        .join(AbnormalCase, AbnormalCase.id == AbnormalCaseAttachment.case_id)
        .join(Inspection, Inspection.id == AbnormalCase.inspection_id)
        .where(AbnormalCaseAttachment.id == attachment_id)
    ).first()
    if not row:
        fail(404, "photo_not_found", "照片不存在")
    attachment, record, inspection = row
    _require_view(record, inspection, user)
    target = UPLOAD_DIR / attachment.stored_name
    if not target.is_file():
        fail(404, "photo_file_missing", "照片檔案不存在，請聯絡系統管理員")
    return FileResponse(target, media_type=attachment.mime_type,
                        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete_case_attachment(attachment_id: str, session: Session = Depends(get_session),
                           user: User = Depends(require_results)):
    row = session.execute(
        select(AbnormalCaseAttachment, AbnormalCase, Inspection)
        .join(AbnormalCase, AbnormalCase.id == AbnormalCaseAttachment.case_id)
        .join(Inspection, Inspection.id == AbnormalCase.inspection_id)
        .where(AbnormalCaseAttachment.id == attachment_id)
    ).first()
    if not row:
        fail(404, "photo_not_found", "照片不存在")
    attachment, record, inspection = row
    _require_view(record, inspection, user)
    if record.status in {"closed", "cancelled"}:
        fail(409, "case_readonly", "已結案或取消的案件照片不可變更")
    if attachment.stage == "correction":
        if record.status != "in_progress" or (not _manager(user) and record.assignee_user_id != user.id):
            fail(403, "permission_denied", "你不能刪除此改善照片")
    elif not _manager(user) or record.status != "pending_review":
        fail(403, "permission_denied", "你不能刪除此複查照片")
    stored_name = attachment.stored_name
    session.delete(attachment)
    _add_history(session, record, user, f"{attachment.stage}_photo_deleted", record.status, record.status,
                 f"刪除照片 {attachment.original_name}")
    add_audit(session, user, "abnormal_case_photo_deleted", "abnormal_case", record.id,
              f"{record.case_number} 刪除照片")
    session.commit()
    (UPLOAD_DIR / stored_name).unlink(missing_ok=True)
    return Response(status_code=204)
