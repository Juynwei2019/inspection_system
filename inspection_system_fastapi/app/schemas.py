"""API 請求驗證。回應由 ORM snapshot serializer 統一組裝。"""
from datetime import date, time
from typing import Literal

from pydantic import BaseModel, Field

ResultType = Literal["normal_abnormal", "normal_abnormal_na"]
ResultValue = Literal["normal", "abnormal", "na"]
UserRole = Literal["system_admin", "inspection_manager", "inspector", "viewer"]


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=100)
    department: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=200)
    role: UserRole = "inspector"
    temporary_password: str = Field(min_length=10, max_length=200)
    is_active: bool = True


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=200)
    role: UserRole | None = None
    is_active: bool | None = None


class PasswordResetInput(BaseModel):
    temporary_password: str = Field(min_length=10, max_length=200)


class LocationCreate(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    area: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=300)
    is_active: bool = True


class LocationUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    area: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=300)
    is_active: bool | None = None


class ItemCreate(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    category: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=300)
    result_type: ResultType = "normal_abnormal_na"
    is_active: bool = True


class ItemUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=300)
    result_type: ResultType | None = None
    is_active: bool | None = None


class MappingInput(BaseModel):
    item_id: str
    sort_order: int = Field(ge=1)
    is_required: bool = True


class MappingUpdate(BaseModel):
    items: list[MappingInput]


class InspectionCreate(BaseModel):
    location_id: str


class DraftResultInput(BaseModel):
    item_id: str
    result: ResultValue | None = None
    note: str = Field(default="", max_length=500)


class DraftUpdate(BaseModel):
    version: int = Field(ge=1)
    inspector: str = Field(default="", max_length=50)
    results: list[DraftResultInput]


class SubmitInput(BaseModel):
    version: int = Field(ge=1)


ScheduleFrequency = Literal["once", "daily", "weekly", "monthly"]


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    location_id: str
    assignee_user_id: str
    frequency: ScheduleFrequency
    weekdays: list[int] = Field(default_factory=list)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    start_time: time
    due_time: time
    effective_from: date
    effective_to: date | None = None
    is_active: bool = True


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    location_id: str | None = None
    assignee_user_id: str | None = None
    frequency: ScheduleFrequency | None = None
    weekdays: list[int] | None = None
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    start_time: time | None = None
    due_time: time | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    is_active: bool | None = None


Severity = Literal["minor", "normal", "major"]


class AbnormalAssignmentInput(BaseModel):
    version: int = Field(ge=1)
    assignee_user_id: str
    due_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    severity: Severity = "normal"


class AbnormalActionInput(BaseModel):
    version: int = Field(ge=1)
    note: str = Field(default="", max_length=1000)


class AbnormalCorrectionInput(BaseModel):
    version: int = Field(ge=1)
    corrective_action: str = Field(min_length=1, max_length=2000)
