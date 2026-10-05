"""巡檢排程、任務產生與任務啟動。"""
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import add_audit, require_inspection, require_maintenance
from ..common import fail, inspection_data, new_id, utc_now
from ..db import get_session
from ..models import InspectionSchedule, InspectionTask, Location, User
from ..schemas import ScheduleCreate, ScheduleUpdate
from .inspections import create_inspection_record

router = APIRouter(prefix="/api/v1", tags=["巡檢排程"])
TAIPEI = ZoneInfo("Asia/Taipei")
ACTIVE_TASK_STATUSES = ("pending", "in_progress")


def local_today() -> date:
    return datetime.now(TAIPEI).date()


def time_text(value: time | str) -> str:
    return value.strftime("%H:%M") if isinstance(value, time) else value[:5]


def date_text(value: date | str | None) -> str | None:
    return value.isoformat() if isinstance(value, date) else value


def utc_at(day: date, clock: str) -> str:
    hour, minute = (int(x) for x in clock.split(":"))
    local = datetime.combine(day, time(hour, minute), tzinfo=TAIPEI)
    return local.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def schedule_values(payload: ScheduleCreate | ScheduleUpdate,
                    existing: InspectionSchedule | None = None) -> dict:
    values = ({
        "name": existing.name, "location_id": existing.location_id,
        "assignee_user_id": existing.assignee_user_id, "frequency": existing.frequency,
        "weekdays": [int(x) for x in existing.weekdays.split(",") if x],
        "day_of_month": existing.day_of_month, "start_time": existing.start_time,
        "due_time": existing.due_time, "effective_from": existing.effective_from,
        "effective_to": existing.effective_to, "is_active": existing.is_active,
    } if existing else {})
    values.update(payload.model_dump(exclude_unset=existing is not None))
    values["name"] = values["name"].strip()
    values["start_time"] = time_text(values["start_time"])
    values["due_time"] = time_text(values["due_time"])
    values["effective_from"] = date_text(values["effective_from"])
    values["effective_to"] = date_text(values.get("effective_to"))
    weekdays = sorted(set(values.get("weekdays") or []))
    if any(day < 1 or day > 7 for day in weekdays):
        fail(422, "invalid_weekdays", "星期必須介於 1 到 7")
    if values["frequency"] == "weekly" and not weekdays:
        fail(422, "weekdays_required", "每週排程至少要選擇一個星期")
    if values["frequency"] == "monthly" and not values.get("day_of_month"):
        fail(422, "day_of_month_required", "每月排程必須設定日期")
    if values["due_time"] <= values["start_time"]:
        fail(422, "invalid_time_range", "截止時間必須晚於開始時間")
    if values.get("effective_to") and values["effective_to"] < values["effective_from"]:
        fail(422, "invalid_date_range", "結束日期不可早於生效日期")
    values["weekdays"] = ",".join(str(x) for x in weekdays) if values["frequency"] == "weekly" else ""
    values["day_of_month"] = values.get("day_of_month") if values["frequency"] == "monthly" else None
    if values["frequency"] == "once":
        values["effective_to"] = values["effective_from"]
    return values


def validate_targets(session: Session, values: dict) -> tuple[Location, User]:
    location = session.get(Location, values["location_id"])
    if not location or not location.is_active:
        fail(422, "location_unavailable", "排程地點不存在或已停用")
    assignee = session.get(User, values["assignee_user_id"])
    if not assignee or not assignee.is_active or assignee.role == "viewer":
        fail(422, "assignee_unavailable", "巡檢人員不存在、已停用或沒有巡檢權限")
    return location, assignee


def target_dates(schedule: InspectionSchedule, today: date) -> list[date]:
    first = max(date.fromisoformat(schedule.effective_from), today - timedelta(days=31))
    last = today + timedelta(days=30)
    if schedule.effective_to:
        last = min(last, date.fromisoformat(schedule.effective_to))
    if first > last:
        return []
    weekdays = {int(x) for x in schedule.weekdays.split(",") if x}
    output = []
    day = first
    while day <= last:
        matched = schedule.frequency == "daily"
        matched = matched or (schedule.frequency == "once" and day.isoformat() == schedule.effective_from)
        matched = matched or (schedule.frequency == "weekly" and day.isoweekday() in weekdays)
        if schedule.frequency == "monthly" and schedule.day_of_month:
            matched = day.day == min(schedule.day_of_month, monthrange(day.year, day.month)[1])
        if matched:
            output.append(day)
        day += timedelta(days=1)
    return output


def sync_schedule_tasks(session: Session, schedule: InspectionSchedule, today: date | None = None) -> None:
    today = today or local_today()
    location = session.get(Location, schedule.location_id)
    assignee = session.get(User, schedule.assignee_user_id)
    usable = bool(schedule.is_active and location and location.is_active and assignee
                  and assignee.is_active and assignee.role != "viewer")
    targets = target_dates(schedule, today) if usable else []
    target_keys = {x.isoformat() for x in targets}
    existing = {x.scheduled_date: x for x in session.scalars(select(InspectionTask).where(
        InspectionTask.schedule_id == schedule.id,
        InspectionTask.scheduled_date >= (today - timedelta(days=31)).isoformat(),
    ))}
    now = utc_now()
    for task in existing.values():
        if task.status == "pending" and task.scheduled_date >= today.isoformat() and task.scheduled_date not in target_keys:
            task.status = "cancelled"
            task.cancelled_at = now
            task.updated_at = now
    if not usable:
        return
    for day in targets:
        key = day.isoformat()
        task = existing.get(key)
        if task and task.status not in ("pending", "cancelled"):
            continue
        if task is None:
            task = InspectionTask(id=new_id(), schedule_id=schedule.id, scheduled_date=key,
                                  status="pending", inspection_id=None, created_at=now,
                                  updated_at=now, started_at=None, completed_at=None, cancelled_at=None)
            session.add(task)
        elif task.status == "cancelled" and task.inspection_id is None:
            task.status = "pending"
            task.cancelled_at = None
        task.window_start_at = utc_at(day, schedule.start_time)
        task.due_at = utc_at(day, schedule.due_time)
        task.location_id = location.id
        task.schedule_name_snapshot = schedule.name
        task.location_code_snapshot = location.code
        task.location_name_snapshot = location.name
        task.area_snapshot = location.area
        task.assignee_user_id = assignee.id
        task.assignee_name_snapshot = assignee.display_name
        task.updated_at = now


def synchronize_all(session: Session) -> None:
    for schedule in session.scalars(select(InspectionSchedule)):
        sync_schedule_tasks(session, schedule)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        fail(409, "schedule_generation_conflict", "排程任務產生衝突，請重新整理")


def schedule_data(schedule: InspectionSchedule, session: Session) -> dict:
    location = session.get(Location, schedule.location_id)
    assignee = session.get(User, schedule.assignee_user_id)
    counts = dict(session.execute(select(InspectionTask.status, func.count()).where(
        InspectionTask.schedule_id == schedule.id).group_by(InspectionTask.status)).all())
    return {"id": schedule.id, "name": schedule.name, "location_id": schedule.location_id,
            "location_name": location.name if location else "已移除地點",
            "assignee_user_id": schedule.assignee_user_id,
            "assignee_name": assignee.display_name if assignee else "已移除人員",
            "frequency": schedule.frequency,
            "weekdays": [int(x) for x in schedule.weekdays.split(",") if x],
            "day_of_month": schedule.day_of_month, "start_time": schedule.start_time,
            "due_time": schedule.due_time, "effective_from": schedule.effective_from,
            "effective_to": schedule.effective_to, "is_active": schedule.is_active,
            "task_counts": counts, "created_at": schedule.created_at, "updated_at": schedule.updated_at}


def task_data(task: InspectionTask, user: User) -> dict:
    now = utc_now()
    overdue = task.status in ACTIVE_TASK_STATUSES and task.due_at < now
    return {"id": task.id, "schedule_id": task.schedule_id,
            "schedule_name": task.schedule_name_snapshot, "scheduled_date": task.scheduled_date,
            "window_start_at": task.window_start_at, "due_at": task.due_at,
            "location_id": task.location_id, "location_code": task.location_code_snapshot,
            "location_name": task.location_name_snapshot, "area": task.area_snapshot,
            "assignee_user_id": task.assignee_user_id, "assignee_name": task.assignee_name_snapshot,
            "status": task.status, "is_overdue": overdue, "inspection_id": task.inspection_id,
            "can_start": task.assignee_user_id == user.id and task.status == "pending"
                         and task.window_start_at <= now,
            "created_at": task.created_at, "started_at": task.started_at,
            "completed_at": task.completed_at}


@router.get("/inspection-schedules/assignees")
def schedule_assignees(session: Session = Depends(get_session),
                       _user: User = Depends(require_maintenance)):
    rows = session.scalars(select(User).where(User.is_active.is_(True), User.role != "viewer")
                           .order_by(User.display_name)).all()
    return {"items": [{"id": x.id, "display_name": x.display_name,
                        "department": x.department, "role": x.role} for x in rows]}


@router.get("/inspection-schedules")
def list_schedules(session: Session = Depends(get_session),
                   _user: User = Depends(require_maintenance)):
    synchronize_all(session)
    rows = session.scalars(select(InspectionSchedule).order_by(
        InspectionSchedule.is_active.desc(), InspectionSchedule.name)).all()
    return {"items": [schedule_data(x, session) for x in rows]}


@router.post("/inspection-schedules", status_code=201)
def create_schedule(payload: ScheduleCreate, session: Session = Depends(get_session),
                    user: User = Depends(require_maintenance)):
    values = schedule_values(payload)
    validate_targets(session, values)
    now = utc_now()
    schedule = InspectionSchedule(id=new_id(), created_by=user.id, created_at=now, updated_at=now, **values)
    session.add(schedule)
    session.flush()
    sync_schedule_tasks(session, schedule)
    add_audit(session, user, "schedule_created", "inspection_schedule", schedule.id,
              f"建立巡檢排程 {schedule.name}")
    session.commit()
    return schedule_data(schedule, session)


@router.patch("/inspection-schedules/{schedule_id}")
def update_schedule(schedule_id: str, payload: ScheduleUpdate,
                    session: Session = Depends(get_session),
                    user: User = Depends(require_maintenance)):
    schedule = session.get(InspectionSchedule, schedule_id)
    if not schedule:
        fail(404, "schedule_not_found", "巡檢排程不存在")
    values = schedule_values(payload, schedule)
    if values["is_active"]:
        validate_targets(session, values)
    for key, value in values.items():
        setattr(schedule, key, value)
    schedule.updated_at = utc_now()
    sync_schedule_tasks(session, schedule)
    add_audit(session, user, "schedule_updated", "inspection_schedule", schedule.id,
              f"更新巡檢排程 {schedule.name}")
    session.commit()
    return schedule_data(schedule, session)


@router.get("/inspection-tasks")
def list_tasks(
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = Query(default=None, pattern=r"^(pending|in_progress|completed|cancelled|overdue)$"),
    query: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    session: Session = Depends(get_session),
    user: User = Depends(require_inspection),
):
    synchronize_all(session)
    start = date_from or local_today()
    end = date_to or start + timedelta(days=7)
    if start > end:
        fail(422, "invalid_date_range", "開始日期不可晚於結束日期")
    conditions = [InspectionTask.scheduled_date >= start.isoformat(),
                  InspectionTask.scheduled_date <= end.isoformat()]
    if user.role == "inspector":
        conditions.append(InspectionTask.assignee_user_id == user.id)
    if query.strip():
        q = f"%{query.strip()}%"
        conditions.append(or_(InspectionTask.schedule_name_snapshot.ilike(q),
                              InspectionTask.location_name_snapshot.ilike(q),
                              InspectionTask.assignee_name_snapshot.ilike(q)))
    now = utc_now()
    overdue = InspectionTask.status.in_(ACTIVE_TASK_STATUSES) & (InspectionTask.due_at < now)
    status_condition = overdue if status == "overdue" else None
    if status and status != "overdue":
        status_condition = InspectionTask.status == status
    stmt = select(InspectionTask).where(*conditions)
    if status_condition is not None:
        stmt = stmt.where(status_condition)
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = session.scalars(stmt.order_by(InspectionTask.scheduled_date, InspectionTask.window_start_at)
                           .offset((page - 1) * page_size).limit(page_size)).all()
    def count(extra):
        return session.scalar(select(func.count()).select_from(InspectionTask).where(*conditions, extra)) or 0
    summary = {"pending": count((InspectionTask.status == "pending") & ~overdue),
               "in_progress": count((InspectionTask.status == "in_progress") & ~overdue),
               "completed": count(InspectionTask.status == "completed"),
               "overdue": count(overdue)}
    return {"items": [task_data(x, user) for x in rows], "total": total,
            "page": page, "page_size": page_size, "summary": summary}


@router.post("/inspection-tasks/{task_id}/start")
def start_task(task_id: str, session: Session = Depends(get_session),
               user: User = Depends(require_inspection)):
    synchronize_all(session)
    task = session.get(InspectionTask, task_id)
    if not task:
        fail(404, "task_not_found", "巡檢任務不存在")
    if task.assignee_user_id != user.id:
        fail(403, "task_not_assigned", "此巡檢任務不是指派給你")
    if task.status == "in_progress" and task.inspection_id:
        record, results, _location = None, None, None
        from .inspections import get_record, get_results, get_attachments
        record = get_record(session, task.inspection_id)
        results = get_results(session, record.id)
        return {"task": task_data(task, user),
                "inspection": inspection_data(record, results, get_attachments(session, results))}
    if task.status != "pending":
        fail(409, "task_not_startable", "此巡檢任務目前無法開始")
    if task.window_start_at > utc_now():
        fail(422, "task_not_open", "尚未到排程開始時間")
    record, results, location = create_inspection_record(session, task.location_id, user)
    now = utc_now()
    task.status = "in_progress"
    task.inspection_id = record.id
    task.started_at = now
    task.updated_at = now
    add_audit(session, user, "scheduled_task_started", "inspection_task", task.id,
              f"開始排程巡檢：{task.schedule_name_snapshot}／{location.name}")
    session.commit()
    return {"task": task_data(task, user), "inspection": inspection_data(record, results, {})}
