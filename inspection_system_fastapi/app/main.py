"""單一 FastAPI 服務：同源提供 HTML 與 API。"""
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .common import inspection_data
from .auth import current_user_optional, get_current_user, require_password_changed
from .db import get_session
from .models import Inspection, InspectionItem, InspectionResult, Location, LocationItem, User
from .routers.authentication import router as authentication_router
from .routers.inspections import router as inspections_router
from .routers.attachments import router as attachments_router
from .routers.abnormal_cases import router as abnormal_cases_router
from .routers.maintenance import router as maintenance_router
from .routers.users import router as users_router
from .routers.schedules import router as schedules_router

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="巡檢系統 API", version="2.2.0")
app.include_router(authentication_router)
app.include_router(maintenance_router, dependencies=[Depends(require_password_changed)])
app.include_router(inspections_router, dependencies=[Depends(require_password_changed)])
app.include_router(attachments_router, dependencies=[Depends(require_password_changed)])
app.include_router(abnormal_cases_router, dependencies=[Depends(require_password_changed)])
app.include_router(users_router, dependencies=[Depends(require_password_changed)])
app.include_router(schedules_router, dependencies=[Depends(require_password_changed)])
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/dashboard", tags=["主頁"])
def dashboard(session: Session = Depends(get_session), user: User = Depends(require_password_changed)):
    available = session.scalar(select(func.count(func.distinct(Location.id)))
                               .select_from(Location).join(LocationItem)
                               .join(InspectionItem, InspectionItem.id == LocationItem.item_id)
                               .where(Location.is_active.is_(True), InspectionItem.is_active.is_(True))) or 0
    own_only = user.role == "inspector"
    can_inspect = user.role != "viewer"
    draft_stmt = select(func.count()).select_from(Inspection).where(Inspection.status == "draft")
    submitted_stmt = select(func.count()).select_from(Inspection).where(Inspection.status == "submitted")
    if own_only:
        draft_stmt = draft_stmt.where(Inspection.inspector_user_id == user.id)
        submitted_stmt = submitted_stmt.where(Inspection.inspector_user_id == user.id)
    draft_count = session.scalar(draft_stmt) or 0 if can_inspect else 0
    submitted_count = session.scalar(submitted_stmt) or 0
    abnormal_exists = select(InspectionResult.id).where(
        InspectionResult.inspection_id == Inspection.id,
        InspectionResult.result == "abnormal",
    ).exists()
    abnormal_stmt = select(func.count()).select_from(Inspection).where(
        Inspection.status == "submitted", abnormal_exists)
    drafts_stmt = select(Inspection).where(Inspection.status == "draft")
    recent_stmt = select(Inspection).where(Inspection.status == "submitted")
    if own_only:
        abnormal_stmt = abnormal_stmt.where(Inspection.inspector_user_id == user.id)
        drafts_stmt = drafts_stmt.where(Inspection.inspector_user_id == user.id)
        recent_stmt = recent_stmt.where(Inspection.inspector_user_id == user.id)
    abnormal_count = session.scalar(abnormal_stmt) or 0
    drafts = session.scalars(drafts_stmt.order_by(Inspection.started_at.desc()).limit(4)).all() if can_inspect else []
    recent = session.scalars(recent_stmt.order_by(Inspection.submitted_at.desc()).limit(4)).all()
    listed = drafts + recent
    grouped = {x.id: [] for x in listed}
    if listed:
        for result in session.scalars(select(InspectionResult).where(
                InspectionResult.inspection_id.in_([x.id for x in listed]))):
            grouped[result.inspection_id].append(result)
    return {"available_locations": available, "draft_count": draft_count,
            "submitted_count": submitted_count, "abnormal_count": abnormal_count,
            "drafts": [inspection_data(x, grouped[x.id]) for x in drafts],
            "recent": [inspection_data(x, grouped[x.id]) for x in recent]}


@app.get("/", include_in_schema=False)
def home(user: User | None = Depends(current_user_optional)):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/login", include_in_schema=False)
def login_page(user: User | None = Depends(current_user_optional)):
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return FileResponse(STATIC_DIR / "login.html", headers={"Cache-Control": "no-store"})
