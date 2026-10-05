"""巡檢項目照片：驗證、儲存、授權讀取與草稿期間刪除。"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import add_audit, require_inspection, require_results
from ..common import attachment_data, fail, new_id, utc_now
from ..db import PROJECT_ROOT, get_session
from ..models import Inspection, InspectionResult, InspectionResultAttachment, User

router = APIRouter(prefix="/api/v1", tags=["巡檢照片"])
UPLOAD_DIR = Path(os.getenv("INSPECTION_UPLOAD_DIR", str(PROJECT_ROOT / "data" / "uploads"))).resolve()
MAX_FILE_BYTES = int(os.getenv("INSPECTION_PHOTO_MAX_BYTES", str(5 * 1024 * 1024)))
MAX_PHOTOS_PER_RESULT = int(os.getenv("INSPECTION_PHOTO_MAX_COUNT", "5"))
MIME_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def _detected_mime(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _result_and_inspection(session: Session, inspection_id: str, item_id: str):
    row = session.execute(
        select(InspectionResult, Inspection)
        .join(Inspection, Inspection.id == InspectionResult.inspection_id)
        .where(Inspection.id == inspection_id, InspectionResult.item_id == item_id)
    ).first()
    if not row:
        fail(404, "inspection_result_not_found", "巡檢項目不存在")
    return row


def _can_view(record: Inspection, user: User) -> None:
    if user.role == "inspector" and record.inspector_user_id != user.id:
        fail(403, "permission_denied", "你只能查看自己的巡檢照片")
    if user.role == "viewer" and record.status != "submitted":
        fail(403, "permission_denied", "查詢人員只能查看已提交的巡檢照片")


def _can_edit(record: Inspection, user: User) -> None:
    if record.status != "draft":
        fail(409, "submitted_record_readonly", "巡檢已提交，照片不可再變更")
    if user.role == "inspector" and record.inspector_user_id != user.id:
        fail(403, "permission_denied", "你只能修改自己的巡檢照片")


@router.post("/inspections/{inspection_id}/results/{item_id}/attachments", status_code=201)
async def upload_attachment(
    inspection_id: str,
    item_id: str,
    photo: UploadFile = File(...),
    session: Session = Depends(get_session),
    user: User = Depends(require_inspection),
):
    result, record = _result_and_inspection(session, inspection_id, item_id)
    _can_edit(record, user)
    count = session.scalar(select(func.count()).select_from(InspectionResultAttachment).where(
        InspectionResultAttachment.inspection_result_id == result.id
    )) or 0
    if count >= MAX_PHOTOS_PER_RESULT:
        fail(422, "photo_limit_reached", f"每個巡檢項目最多 {MAX_PHOTOS_PER_RESULT} 張照片")

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
    attachment = InspectionResultAttachment(
        id=attachment_id, inspection_result_id=result.id, original_name=original_name,
        stored_name=stored_name, mime_type=mime_type, file_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(), uploaded_by=user.id, created_at=utc_now(),
    )
    session.add(attachment)
    add_audit(session, user, "inspection_photo_uploaded", "inspection", record.id,
              f"新增巡檢照片：{result.item_name_snapshot}")
    try:
        session.commit()
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return attachment_data(attachment)


@router.get("/attachments/{attachment_id}/content")
def attachment_content(attachment_id: str, session: Session = Depends(get_session),
                       user: User = Depends(require_results)):
    row = session.execute(
        select(InspectionResultAttachment, Inspection)
        .join(InspectionResult, InspectionResult.id == InspectionResultAttachment.inspection_result_id)
        .join(Inspection, Inspection.id == InspectionResult.inspection_id)
        .where(InspectionResultAttachment.id == attachment_id)
    ).first()
    if not row:
        fail(404, "photo_not_found", "照片不存在")
    attachment, record = row
    _can_view(record, user)
    target = UPLOAD_DIR / attachment.stored_name
    if not target.is_file():
        fail(404, "photo_file_missing", "照片檔案不存在，請聯絡系統管理員")
    return FileResponse(target, media_type=attachment.mime_type,
                        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete_attachment(attachment_id: str, session: Session = Depends(get_session),
                      user: User = Depends(require_inspection)):
    row = session.execute(
        select(InspectionResultAttachment, InspectionResult, Inspection)
        .join(InspectionResult, InspectionResult.id == InspectionResultAttachment.inspection_result_id)
        .join(Inspection, Inspection.id == InspectionResult.inspection_id)
        .where(InspectionResultAttachment.id == attachment_id)
    ).first()
    if not row:
        fail(404, "photo_not_found", "照片不存在")
    attachment, result, record = row
    _can_edit(record, user)
    stored_name = attachment.stored_name
    session.delete(attachment)
    add_audit(session, user, "inspection_photo_deleted", "inspection", record.id,
              f"刪除巡檢照片：{result.item_name_snapshot}")
    session.commit()
    (UPLOAD_DIR / stored_name).unlink(missing_ok=True)
    return Response(status_code=204)
