"""add inspection scheduling

Revision ID: e6b32a7f9c11
Revises: d4a91e7c2b30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6b32a7f9c11"
down_revision: Union[str, None] = "d4a91e7c2b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inspection_schedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("location_id", sa.String(36), nullable=False),
        sa.Column("assignee_user_id", sa.String(36), nullable=False),
        sa.Column("frequency", sa.String(12), nullable=False),
        sa.Column("weekdays", sa.String(20), nullable=False, server_default=""),
        sa.Column("day_of_month", sa.Integer()),
        sa.Column("start_time", sa.String(5), nullable=False),
        sa.Column("due_time", sa.String(5), nullable=False),
        sa.Column("effective_from", sa.String(10), nullable=False),
        sa.Column("effective_to", sa.String(10)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(36)),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.CheckConstraint(
            "frequency IN ('once', 'daily', 'weekly', 'monthly')",
            name="valid_schedule_frequency",
        ),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assignee_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_inspection_schedules_active_dates",
        "inspection_schedules",
        ["is_active", "effective_from", "effective_to"],
    )
    op.create_table(
        "inspection_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("schedule_id", sa.String(36), nullable=False),
        sa.Column("scheduled_date", sa.String(10), nullable=False),
        sa.Column("window_start_at", sa.String(32), nullable=False),
        sa.Column("due_at", sa.String(32), nullable=False),
        sa.Column("location_id", sa.String(36), nullable=False),
        sa.Column("schedule_name_snapshot", sa.String(120), nullable=False),
        sa.Column("location_code_snapshot", sa.String(80), nullable=False),
        sa.Column("location_name_snapshot", sa.String(100), nullable=False),
        sa.Column("area_snapshot", sa.String(100), nullable=False, server_default=""),
        sa.Column("assignee_user_id", sa.String(36)),
        sa.Column("assignee_name_snapshot", sa.String(100), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("inspection_id", sa.String(36), unique=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("started_at", sa.String(32)),
        sa.Column("completed_at", sa.String(32)),
        sa.Column("cancelled_at", sa.String(32)),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'cancelled')",
            name="valid_task_status",
        ),
        sa.ForeignKeyConstraint(["schedule_id"], ["inspection_schedules.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assignee_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["inspection_id"], ["inspections.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("schedule_id", "scheduled_date", name="uq_schedule_task_date"),
    )
    op.create_index(
        "ix_inspection_tasks_assignee_date",
        "inspection_tasks",
        ["assignee_user_id", "scheduled_date", "status"],
    )
    op.create_index("ix_inspection_tasks_status_due", "inspection_tasks", ["status", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_inspection_tasks_status_due", table_name="inspection_tasks")
    op.drop_index("ix_inspection_tasks_assignee_date", table_name="inspection_tasks")
    op.drop_table("inspection_tasks")
    op.drop_index("ix_inspection_schedules_active_dates", table_name="inspection_schedules")
    op.drop_table("inspection_schedules")
