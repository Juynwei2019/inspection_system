"""巡檢主檔、設定與歷史快照。"""
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('system_admin', 'inspection_manager', 'inspector', 'viewer')",
            name="valid_user_role",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="inspector")
    department: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[str | None] = mapped_column(String(32))
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)
    last_login_at: Mapped[str | None] = mapped_column(String(32))


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_user_active", "user_id", "revoked_at", "expires_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[str] = mapped_column(String(32), nullable=False)
    last_seen_at: Mapped[str] = mapped_column(String(32), nullable=False)
    revoked_at: Mapped[str | None] = mapped_column(String(32))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_created", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    username_snapshot: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    target_id: Mapped[str | None] = mapped_column(String(80))
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)


class Location(Base):
    __tablename__ = "locations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    area: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)


class InspectionItem(Base):
    __tablename__ = "inspection_items"
    __table_args__ = (CheckConstraint("result_type IN ('normal_abnormal', 'normal_abnormal_na')", name="valid_result_type"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    result_type: Mapped[str] = mapped_column(String(24), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)


class LocationItem(Base):
    __tablename__ = "location_items"
    __table_args__ = (UniqueConstraint("location_id", "sort_order", name="uq_location_sort_order"),)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id", ondelete="RESTRICT"), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("inspection_items.id", ondelete="RESTRICT"), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Inspection(Base):
    __tablename__ = "inspections"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'submitted')", name="valid_inspection_status"),
        Index("ix_inspections_status_submitted", "status", "submitted_at"),
        Index("ix_inspections_location_submitted", "location_id", "submitted_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    number: Mapped[str | None] = mapped_column(String(50), unique=True)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False)
    location_code_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    location_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    area_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    inspector: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    inspector_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    inspector_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[str] = mapped_column(String(32), nullable=False)
    submitted_at: Mapped[str | None] = mapped_column(String(32))


class InspectionSchedule(Base):
    __tablename__ = "inspection_schedules"
    __table_args__ = (
        CheckConstraint("frequency IN ('once', 'daily', 'weekly', 'monthly')", name="valid_schedule_frequency"),
        Index("ix_inspection_schedules_active_dates", "is_active", "effective_from", "effective_to"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False)
    assignee_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    frequency: Mapped[str] = mapped_column(String(12), nullable=False)
    weekdays: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    day_of_month: Mapped[int | None] = mapped_column(Integer)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)
    due_time: Mapped[str] = mapped_column(String(5), nullable=False)
    effective_from: Mapped[str] = mapped_column(String(10), nullable=False)
    effective_to: Mapped[str | None] = mapped_column(String(10))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)


class InspectionTask(Base):
    __tablename__ = "inspection_tasks"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'in_progress', 'completed', 'cancelled')", name="valid_task_status"),
        UniqueConstraint("schedule_id", "scheduled_date", name="uq_schedule_task_date"),
        Index("ix_inspection_tasks_assignee_date", "assignee_user_id", "scheduled_date", "status"),
        Index("ix_inspection_tasks_status_due", "status", "due_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    schedule_id: Mapped[str] = mapped_column(
        ForeignKey("inspection_schedules.id", ondelete="RESTRICT"), nullable=False
    )
    scheduled_date: Mapped[str] = mapped_column(String(10), nullable=False)
    window_start_at: Mapped[str] = mapped_column(String(32), nullable=False)
    due_at: Mapped[str] = mapped_column(String(32), nullable=False)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False)
    schedule_name_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    location_code_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    location_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    area_snapshot: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    assignee_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assignee_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    inspection_id: Mapped[str | None] = mapped_column(
        ForeignKey("inspections.id", ondelete="RESTRICT"), unique=True
    )
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[str | None] = mapped_column(String(32))
    completed_at: Mapped[str | None] = mapped_column(String(32))
    cancelled_at: Mapped[str | None] = mapped_column(String(32))


class InspectionResult(Base):
    __tablename__ = "inspection_results"
    __table_args__ = (
        UniqueConstraint("inspection_id", "item_id", name="uq_inspection_item"),
        CheckConstraint("result IN ('normal', 'abnormal', 'na') OR result IS NULL", name="valid_inspection_result"),
        Index("ix_inspection_results_inspection", "inspection_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    inspection_id: Mapped[str] = mapped_column(ForeignKey("inspections.id", ondelete="RESTRICT"), nullable=False)
    item_id: Mapped[str] = mapped_column(ForeignKey("inspection_items.id", ondelete="RESTRICT"), nullable=False)
    item_code_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    item_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    category_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    description_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    result_type_snapshot: Mapped[str] = mapped_column(String(24), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    result: Mapped[str | None] = mapped_column(String(10))
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class InspectionResultAttachment(Base):
    __tablename__ = "inspection_result_attachments"
    __table_args__ = (
        Index("ix_result_attachments_result", "inspection_result_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    inspection_result_id: Mapped[str] = mapped_column(
        ForeignKey("inspection_results.id", ondelete="CASCADE"), nullable=False
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)


class AbnormalCase(Base):
    __tablename__ = "abnormal_cases"
    __table_args__ = (
        CheckConstraint("severity IN ('minor', 'normal', 'major')", name="valid_abnormal_severity"),
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'pending_review', 'closed', 'cancelled')",
            name="valid_abnormal_status",
        ),
        UniqueConstraint("inspection_result_id", name="uq_abnormal_case_result"),
        Index("ix_abnormal_cases_status_due", "status", "due_date"),
        Index("ix_abnormal_cases_assignee_status", "assignee_user_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    inspection_id: Mapped[str] = mapped_column(ForeignKey("inspections.id", ondelete="RESTRICT"), nullable=False)
    inspection_result_id: Mapped[str] = mapped_column(
        ForeignKey("inspection_results.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(12), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    assignee_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assignee_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    due_date: Mapped[str | None] = mapped_column(String(10))
    corrective_action: Mapped[str] = mapped_column(Text, nullable=False, default="")
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    closed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)
    closed_at: Mapped[str | None] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AbnormalCaseHistory(Base):
    __tablename__ = "abnormal_case_histories"
    __table_args__ = (Index("ix_abnormal_history_case_created", "case_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("abnormal_cases.id", ondelete="CASCADE"), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)


class AbnormalCaseAttachment(Base):
    __tablename__ = "abnormal_case_attachments"
    __table_args__ = (
        CheckConstraint("stage IN ('correction', 'review')", name="valid_abnormal_attachment_stage"),
        Index("ix_abnormal_attachments_case_stage", "case_id", "stage", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("abnormal_cases.id", ondelete="CASCADE"), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
