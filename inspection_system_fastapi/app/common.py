"""序列化與 HTTP 錯誤工具。"""
from datetime import datetime, timezone

from fastapi import HTTPException

from .models import (AbnormalCase, Inspection, InspectionItem, InspectionResult,
                     InspectionResultAttachment, Location, LocationItem)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    from uuid import uuid4

    return str(uuid4())


def fail(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def location_data(x: Location) -> dict:
    return {"id": x.id, "code": x.code, "name": x.name, "area": x.area,
            "description": x.description, "is_active": x.is_active,
            "created_at": x.created_at, "updated_at": x.updated_at}


def item_data(x: InspectionItem) -> dict:
    return {"id": x.id, "code": x.code, "name": x.name, "category": x.category,
            "description": x.description, "result_type": x.result_type, "is_active": x.is_active,
            "created_at": x.created_at, "updated_at": x.updated_at}


def mapping_data(x: LocationItem) -> dict:
    return {"item_id": x.item_id, "sort_order": x.sort_order, "is_required": x.is_required}


def attachment_data(x: InspectionResultAttachment) -> dict:
    return {"id": x.id, "original_name": x.original_name, "mime_type": x.mime_type,
            "file_size": x.file_size, "created_at": x.created_at,
            "content_url": f"/api/v1/attachments/{x.id}/content"}


def result_data(x: InspectionResult, attachments: list[InspectionResultAttachment] | None = None,
                abnormal_case: AbnormalCase | None = None) -> dict:
    return {"id": x.id, "item_id": x.item_id, "code": x.item_code_snapshot,
            "name": x.item_name_snapshot, "category": x.category_snapshot,
            "description": x.description_snapshot, "result_type": x.result_type_snapshot,
            "sort_order": x.sort_order, "is_required": x.is_required,
            "result": x.result, "note": x.note,
            "abnormal_case": ({"id": abnormal_case.id, "case_number": abnormal_case.case_number,
                               "status": abnormal_case.status, "severity": abnormal_case.severity}
                              if abnormal_case else None),
            "attachments": [attachment_data(a) for a in (attachments or [])]}


def inspection_data(x: Inspection, results: list[InspectionResult] | None = None,
                    attachments: dict[str, list[InspectionResultAttachment]] | None = None,
                    abnormal_cases: dict[str, AbnormalCase] | None = None) -> dict:
    data = {"id": x.id, "number": x.number, "location_id": x.location_id,
            "location_code": x.location_code_snapshot, "location_name": x.location_name_snapshot,
            "area": x.area_snapshot, "inspector": x.inspector_name_snapshot or x.inspector,
            "inspector_user_id": x.inspector_user_id, "status": x.status,
            "version": x.version, "started_at": x.started_at, "submitted_at": x.submitted_at}
    if results is not None:
        ordered = sorted(results, key=lambda r: r.sort_order)
        data["results"] = [result_data(r, (attachments or {}).get(r.id, []),
                                       (abnormal_cases or {}).get(r.id)) for r in ordered]
        data["item_count"] = len(ordered)
        data["answered_count"] = sum(r.result is not None for r in ordered)
        data["abnormal_count"] = sum(r.result == "abnormal" for r in ordered)
    return data
