"""巡檢草稿、提交與伺服器端結果查詢。"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..common import fail, inspection_data, new_id, utc_now
from ..auth import add_audit, require_inspection, require_results
from ..db import get_session
from ..models import (AbnormalCase, AbnormalCaseHistory, Inspection, InspectionItem,
                      InspectionResult, InspectionResultAttachment, InspectionTask,
                      Location, LocationItem, User)
from ..schemas import DraftUpdate, InspectionCreate, SubmitInput

router = APIRouter(prefix="/api/v1/inspections", tags=["巡檢與查詢"])
TAIPEI = ZoneInfo("Asia/Taipei")


def get_record(session: Session, inspection_id: str) -> Inspection:
    record = session.get(Inspection, inspection_id)
    if record is None:
        fail(404, "inspection_not_found", "巡檢紀錄不存在")
    return record


def get_results(session: Session, inspection_id: str) -> list[InspectionResult]:
    return list(session.scalars(select(InspectionResult)
                                .where(InspectionResult.inspection_id == inspection_id)
                                .order_by(InspectionResult.sort_order)))


def get_attachments(session: Session, results: list[InspectionResult]):
    grouped: dict[str, list[InspectionResultAttachment]] = defaultdict(list)
    if results:
        rows = session.scalars(select(InspectionResultAttachment).where(
            InspectionResultAttachment.inspection_result_id.in_([x.id for x in results])
        ).order_by(InspectionResultAttachment.created_at, InspectionResultAttachment.id))
        for attachment in rows:
            grouped[attachment.inspection_result_id].append(attachment)
    return grouped


def get_abnormal_cases(session: Session, results: list[InspectionResult]) -> dict[str, AbnormalCase]:
    if not results:
        return {}
    rows = session.scalars(select(AbnormalCase).where(
        AbnormalCase.inspection_result_id.in_([x.id for x in results])
    )).all()
    return {x.inspection_result_id: x for x in rows}


def as_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def create_inspection_record(session: Session, location_id: str, user: User):
    """建立巡檢快照；由呼叫端決定何時 commit。"""
    location = session.get(Location, location_id)
    if not location or not location.is_active:
        fail(422, "location_unavailable", "此地點不存在或已停用")
    rows = session.execute(
        select(LocationItem, InspectionItem)
        .join(InspectionItem, InspectionItem.id == LocationItem.item_id)
        .where(LocationItem.location_id == location.id, InspectionItem.is_active.is_(True))
        .order_by(LocationItem.sort_order)
    ).all()
    if not rows:
        fail(422, "no_active_items", "此地點沒有可巡檢的項目")
    record = Inspection(id=new_id(), location_id=location.id,
                        location_code_snapshot=location.code, location_name_snapshot=location.name,
                        area_snapshot=location.area, inspector=user.display_name,
                        inspector_user_id=user.id, inspector_name_snapshot=user.display_name,
                        status="draft", version=1, started_at=utc_now())
    results = [InspectionResult(id=new_id(), inspection_id=record.id, item_id=item.id,
                                item_code_snapshot=item.code, item_name_snapshot=item.name,
                                category_snapshot=item.category, description_snapshot=item.description,
                                result_type_snapshot=item.result_type, sort_order=link.sort_order,
                                is_required=link.is_required, result=None, note="")
               for link, item in rows]
    session.add(record)
    session.add_all(results)
    return record, results, location


@router.post("", status_code=201)
def create_inspection(payload: InspectionCreate, session: Session = Depends(get_session),
                      user: User = Depends(require_inspection)):
    record, results, location = create_inspection_record(session, payload.location_id, user)
    add_audit(session, user, "inspection_created", "inspection", record.id,
              f"建立 {location.name} 巡檢草稿")
    session.commit()
    return inspection_data(record, results, {})


@router.get("")
def list_inspections(
    status: str = Query(default="submitted", pattern=r"^(draft|submitted)$"),
    date_from: date | None = None,
    date_to: date | None = None,
    location_id: str | None = None,
    query: str = Query(default="", max_length=100),
    has_abnormal: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    session: Session = Depends(get_session),
    user: User = Depends(require_results),
):
    if date_from and date_to and date_from > date_to:
        fail(422, "invalid_date_range", "開始日期不可晚於結束日期")
    if user.role == "viewer" and status != "submitted":
        fail(403, "permission_denied", "查詢人員只能查看已提交的巡檢結果")
    stmt = select(Inspection).where(Inspection.status == status)
    if user.role == "inspector":
        stmt = stmt.where(Inspection.inspector_user_id == user.id)
    if date_from:
        start = as_utc(datetime.combine(date_from, time.min, tzinfo=TAIPEI))
        stmt = stmt.where(Inspection.submitted_at >= start if status == "submitted" else Inspection.started_at >= start)
    if date_to:
        end = as_utc(datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=TAIPEI))
        stmt = stmt.where(Inspection.submitted_at < end if status == "submitted" else Inspection.started_at < end)
    if location_id:
        stmt = stmt.where(Inspection.location_id == location_id)
    if query.strip():
        q = f"%{query.strip()}%"
        stmt = stmt.where(or_(Inspection.number.ilike(q), Inspection.inspector.ilike(q),
                              Inspection.location_name_snapshot.ilike(q), Inspection.location_code_snapshot.ilike(q)))
    if has_abnormal is not None:
        abnormal = select(InspectionResult.id).where(
            InspectionResult.inspection_id == Inspection.id,
            InspectionResult.result == "abnormal",
        ).exists()
        stmt = stmt.where(abnormal if has_abnormal else ~abnormal)
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    abnormal_exists = select(InspectionResult.id).where(
        InspectionResult.inspection_id == Inspection.id,
        InspectionResult.result == "abnormal",
    ).exists()
    abnormal_count = session.scalar(select(func.count()).select_from(
        stmt.where(abnormal_exists).order_by(None).subquery())) or 0
    rows = session.scalars(stmt.order_by(Inspection.submitted_at.desc() if status == "submitted"
                                               else Inspection.started_at.desc(), Inspection.id.desc())
                           .offset((page - 1) * page_size).limit(page_size)).all()
    # 單次讀出當頁的逐項結果，避免每一筆紀錄再查一次。
    grouped: dict[str, list[InspectionResult]] = defaultdict(list)
    if rows:
        for result in session.scalars(select(InspectionResult)
                                      .where(InspectionResult.inspection_id.in_([x.id for x in rows]))):
            grouped[result.inspection_id].append(result)
    attachments = get_attachments(session, [result for values in grouped.values() for result in values])
    return {"items": [inspection_data(x, grouped[x.id], attachments) for x in rows], "total": total,
            "normal_count": total - abnormal_count, "abnormal_count": abnormal_count,
            "page": page, "page_size": page_size}


@router.get("/{inspection_id}")
def get_inspection(inspection_id: str, session: Session = Depends(get_session),
                   user: User = Depends(require_results)):
    record = get_record(session, inspection_id)
    if user.role == "inspector" and record.inspector_user_id != user.id:
        fail(403, "permission_denied", "你只能查看自己的巡檢紀錄")
    if user.role == "viewer" and record.status != "submitted":
        fail(403, "permission_denied", "查詢人員只能查看已提交的巡檢結果")
    results = get_results(session, record.id)
    return inspection_data(record, results, get_attachments(session, results),
                           get_abnormal_cases(session, results))


@router.patch("/{inspection_id}/draft")
def update_draft(inspection_id: str, payload: DraftUpdate, session: Session = Depends(get_session),
                 user: User = Depends(require_inspection)):
    record = get_record(session, inspection_id)
    if user.role == "inspector" and record.inspector_user_id != user.id:
        fail(403, "permission_denied", "你只能修改自己的巡檢草稿")
    if record.status != "draft" or record.version != payload.version:
        fail(409, "draft_conflict", "草稿已提交或已有較新的修改，請重新讀取")
    results = get_results(session, record.id)
    by_id = {x.item_id: x for x in results}
    submitted = {x.item_id: x for x in payload.results}
    if len(submitted) != len(payload.results) or set(submitted) != set(by_id):
        fail(422, "result_set_mismatch", "草稿項目與建立時的清單不一致")
    for item_id, value in submitted.items():
        saved = by_id[item_id]
        if value.result == "na" and saved.result_type_snapshot == "normal_abnormal":
            fail(422, "result_not_allowed", f"{saved.item_name_snapshot} 不允許選擇不適用")
    updated = session.execute(update(Inspection).where(
        Inspection.id == record.id, Inspection.status == "draft", Inspection.version == payload.version,
    ).values(inspector=user.display_name, inspector_user_id=user.id,
             inspector_name_snapshot=user.display_name, version=payload.version + 1))
    if updated.rowcount != 1:
        session.rollback()
        fail(409, "draft_conflict", "草稿已有較新的修改，請重新讀取")
    for item_id, value in submitted.items():
        by_id[item_id].result = value.result
        by_id[item_id].note = value.note.strip()
    session.commit()
    session.refresh(record)
    return inspection_data(record, results, get_attachments(session, results))


@router.post("/{inspection_id}/submit")
def submit_inspection(inspection_id: str, payload: SubmitInput, session: Session = Depends(get_session),
                      user: User = Depends(require_inspection)):
    record = get_record(session, inspection_id)
    if user.role == "inspector" and record.inspector_user_id != user.id:
        fail(403, "permission_denied", "你只能提交自己的巡檢草稿")
    if record.status != "draft" or record.version != payload.version:
        fail(409, "draft_conflict", "草稿已提交或已有較新的修改，請重新讀取")
    results = get_results(session, record.id)
    if not record.inspector.strip():
        fail(422, "inspector_required", "請填寫巡檢人員")
    for item in results:
        if item.is_required and item.result is None:
            fail(422, "required_result_missing", f"{item.item_name_snapshot} 尚未檢查")
        if item.result == "abnormal" and not item.note.strip():
            fail(422, "abnormal_note_required", f"{item.item_name_snapshot} 須填寫異常說明")
    submitted_at = utc_now()
    number = f"INSP-{submitted_at[:10].replace('-', '')}-{record.id.replace('-', '')[:12].upper()}"
    updated = session.execute(update(Inspection).where(
        Inspection.id == record.id, Inspection.status == "draft", Inspection.version == payload.version,
    ).values(status="submitted", submitted_at=submitted_at, number=number, version=payload.version + 1))
    if updated.rowcount != 1:
        session.rollback()
        fail(409, "draft_conflict", "草稿已有較新的修改，請重新讀取")
    for item in results:
        if item.result != "abnormal":
            continue
        case_id = new_id()
        case_number = f"ABN-{submitted_at[:10].replace('-', '')}-{case_id.replace('-', '')[:12].upper()}"
        abnormal_case = AbnormalCase(
            id=case_id, case_number=case_number, inspection_id=record.id,
            inspection_result_id=item.id, title=f"{item.item_name_snapshot}異常",
            description=item.note.strip(), severity="normal", status="pending",
            assignee_user_id=None, assignee_name_snapshot="", due_date=None,
            corrective_action="", review_note="", created_by=user.id, closed_by=None,
            created_at=submitted_at, updated_at=submitted_at, closed_at=None, version=1,
        )
        session.add(abnormal_case)
        session.add(AbnormalCaseHistory(
            id=new_id(), case_id=case_id, actor_user_id=user.id,
            actor_name_snapshot=user.display_name, action="created",
            from_status=None, to_status="pending", note=item.note.strip(), created_at=submitted_at,
        ))
    add_audit(session, user, "inspection_submitted", "inspection", record.id,
              f"提交巡檢 {number}")
    task = session.scalar(select(InspectionTask).where(InspectionTask.inspection_id == record.id))
    if task:
        task.status = "completed"
        task.completed_at = submitted_at
        task.updated_at = submitted_at
    session.commit()
    session.refresh(record)
    return inspection_data(record, results, get_attachments(session, results))
