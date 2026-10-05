"""地點、項目與地點檢查清單。"""
from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import add_audit, require_maintenance
from ..common import fail, item_data, location_data, mapping_data, new_id, utc_now
from ..db import get_session
from ..models import InspectionItem, Location, LocationItem, User
from ..schemas import ItemCreate, ItemUpdate, LocationCreate, LocationUpdate, MappingUpdate

router = APIRouter(prefix="/api/v1", tags=["維護模組"])


def commit_or_conflict(session: Session):
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        fail(409, "duplicate_or_conflict", "代碼已存在或資料關聯衝突")


@router.get("/bootstrap")
def bootstrap(session: Session = Depends(get_session)):
    locations = session.scalars(select(Location).order_by(Location.code)).all()
    items = session.scalars(select(InspectionItem).order_by(InspectionItem.code)).all()
    links = session.scalars(select(LocationItem).order_by(LocationItem.location_id, LocationItem.sort_order)).all()
    return {"locations": [location_data(x) for x in locations],
            "items": [item_data(x) for x in items],
            "links": {location.id: [mapping_data(x) for x in links if x.location_id == location.id]
                      for location in locations}}


@router.get("/locations")
def locations(active_only: bool = False, session: Session = Depends(get_session)):
    query = select(Location)
    if active_only:
        query = query.where(Location.is_active.is_(True))
    return {"items": [location_data(x) for x in session.scalars(query.order_by(Location.code))]}


@router.post("/locations", status_code=201)
def create_location(payload: LocationCreate, session: Session = Depends(get_session),
                    user: User = Depends(require_maintenance)):
    now = utc_now()
    data = payload.model_dump()
    data["code"] = data["code"].upper()
    data["name"] = data["name"].strip()
    if not data["name"]:
        fail(422, "invalid_name", "地點名稱不可空白")
    location = Location(id=new_id(), created_at=now, updated_at=now, **data)
    session.add(location)
    add_audit(session, user, "location_created", "location", location.id, f"建立地點 {location.code}")
    commit_or_conflict(session)
    return location_data(location)


@router.patch("/locations/{location_id}")
def update_location(location_id: str, payload: LocationUpdate, session: Session = Depends(get_session),
                    user: User = Depends(require_maintenance)):
    location = session.get(Location, location_id)
    if not location:
        fail(404, "location_not_found", "巡檢地點不存在")
    changes = payload.model_dump(exclude_unset=True)
    if any(v is None for v in changes.values()):
        fail(422, "null_not_allowed", "欄位不可設為 null")
    if "name" in changes and not changes["name"].strip():
        fail(422, "invalid_name", "地點名稱不可空白")
    if "code" in changes:
        changes["code"] = changes["code"].upper()
    for key, value in changes.items():
        setattr(location, key, value.strip() if isinstance(value, str) else value)
    location.updated_at = utc_now()
    add_audit(session, user, "location_updated", "location", location.id, f"更新地點 {location.code}")
    commit_or_conflict(session)
    return location_data(location)


@router.get("/items")
def items(active_only: bool = False, session: Session = Depends(get_session)):
    query = select(InspectionItem)
    if active_only:
        query = query.where(InspectionItem.is_active.is_(True))
    return {"items": [item_data(x) for x in session.scalars(query.order_by(InspectionItem.code))]}


@router.post("/items", status_code=201)
def create_item(payload: ItemCreate, session: Session = Depends(get_session),
                user: User = Depends(require_maintenance)):
    now = utc_now()
    data = payload.model_dump()
    data["code"] = data["code"].upper()
    data["name"] = data["name"].strip()
    if not data["name"]:
        fail(422, "invalid_name", "項目名稱不可空白")
    item = InspectionItem(id=new_id(), created_at=now, updated_at=now, **data)
    session.add(item)
    add_audit(session, user, "item_created", "inspection_item", item.id, f"建立巡檢項目 {item.code}")
    commit_or_conflict(session)
    return item_data(item)


@router.patch("/items/{item_id}")
def update_item(item_id: str, payload: ItemUpdate, session: Session = Depends(get_session),
                user: User = Depends(require_maintenance)):
    item = session.get(InspectionItem, item_id)
    if not item:
        fail(404, "item_not_found", "巡檢項目不存在")
    changes = payload.model_dump(exclude_unset=True)
    if any(v is None for v in changes.values()):
        fail(422, "null_not_allowed", "欄位不可設為 null")
    if "name" in changes and not changes["name"].strip():
        fail(422, "invalid_name", "項目名稱不可空白")
    if "code" in changes:
        changes["code"] = changes["code"].upper()
    for key, value in changes.items():
        setattr(item, key, value.strip() if isinstance(value, str) else value)
    item.updated_at = utc_now()
    add_audit(session, user, "item_updated", "inspection_item", item.id, f"更新巡檢項目 {item.code}")
    commit_or_conflict(session)
    return item_data(item)


@router.get("/locations/{location_id}/items")
def get_location_items(location_id: str, session: Session = Depends(get_session)):
    if not session.get(Location, location_id):
        fail(404, "location_not_found", "巡檢地點不存在")
    links = session.scalars(select(LocationItem).where(LocationItem.location_id == location_id)
                            .order_by(LocationItem.sort_order)).all()
    return {"items": [mapping_data(x) for x in links]}


@router.put("/locations/{location_id}/items")
def put_location_items(location_id: str, payload: MappingUpdate, session: Session = Depends(get_session),
                       user: User = Depends(require_maintenance)):
    if not session.get(Location, location_id):
        fail(404, "location_not_found", "巡檢地點不存在")
    ids = [x.item_id for x in payload.items]
    orders = [x.sort_order for x in payload.items]
    if len(ids) != len(set(ids)) or sorted(orders) != list(range(1, len(orders) + 1)):
        fail(422, "invalid_mapping", "項目不可重複，顯示順序須由 1 連續排列")
    if ids:
        existing = set(session.scalars(select(InspectionItem.id).where(InspectionItem.id.in_(ids))))
        if existing != set(ids):
            fail(422, "item_not_found", "地點設定包含不存在的項目")
    session.execute(delete(LocationItem).where(LocationItem.location_id == location_id))
    session.flush()
    session.add_all(LocationItem(location_id=location_id, item_id=x.item_id,
                                 sort_order=x.sort_order, is_required=x.is_required) for x in payload.items)
    add_audit(session, user, "location_items_updated", "location", location_id,
              f"更新地點檢查清單，共 {len(payload.items)} 項")
    commit_or_conflict(session)
    return {"items": [mapping_data(x) for x in sorted(payload.items, key=lambda x: x.sort_order)]}
