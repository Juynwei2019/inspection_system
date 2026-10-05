"""add abnormal case tracking

Revision ID: d4a91e7c2b30
Revises: b7d2f94a1c6e
"""
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "d4a91e7c2b30"
down_revision: Union[str, None] = "b7d2f94a1c6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "abnormal_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_number", sa.String(50), nullable=False, unique=True),
        sa.Column("inspection_id", sa.String(36), nullable=False),
        sa.Column("inspection_result_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(12), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("assignee_user_id", sa.String(36)),
        sa.Column("assignee_name_snapshot", sa.String(100), nullable=False, server_default=""),
        sa.Column("due_date", sa.String(10)),
        sa.Column("corrective_action", sa.Text(), nullable=False, server_default=""),
        sa.Column("review_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(36)),
        sa.Column("closed_by", sa.String(36)),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("closed_at", sa.String(32)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("severity IN ('minor', 'normal', 'major')", name="valid_abnormal_severity"),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'pending_review', 'closed', 'cancelled')",
            name="valid_abnormal_status",
        ),
        sa.ForeignKeyConstraint(["inspection_id"], ["inspections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inspection_result_id"], ["inspection_results.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assignee_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["closed_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("inspection_result_id", name="uq_abnormal_case_result"),
    )
    op.create_index("ix_abnormal_cases_status_due", "abnormal_cases", ["status", "due_date"])
    op.create_index("ix_abnormal_cases_assignee_status", "abnormal_cases", ["assignee_user_id", "status"])
    op.create_table(
        "abnormal_case_histories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("actor_user_id", sa.String(36)),
        sa.Column("actor_name_snapshot", sa.String(100), nullable=False, server_default=""),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("from_status", sa.String(20)),
        sa.Column("to_status", sa.String(20)),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["abnormal_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_abnormal_history_case_created", "abnormal_case_histories", ["case_id", "created_at"])
    op.create_table(
        "abnormal_case_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("stored_name", sa.String(80), nullable=False, unique=True),
        sa.Column("mime_type", sa.String(50), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("uploaded_by", sa.String(36)),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.CheckConstraint("stage IN ('correction', 'review')", name="valid_abnormal_attachment_stage"),
        sa.ForeignKeyConstraint(["case_id"], ["abnormal_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_abnormal_attachments_case_stage", "abnormal_case_attachments", ["case_id", "stage", "created_at"]
    )
    connection = op.get_bind()
    historical = connection.execute(sa.text("""
        SELECT r.id AS result_id, r.inspection_id, r.item_name_snapshot, r.note,
               i.inspector_user_id, i.inspector_name_snapshot, i.inspector,
               COALESCE(i.submitted_at, i.started_at) AS created_at
          FROM inspection_results r
          JOIN inspections i ON i.id = r.inspection_id
         WHERE i.status = 'submitted' AND r.result = 'abnormal'
    """)).mappings()
    for row in historical:
        case_id = str(uuid4())
        compact_id = case_id.replace("-", "")[:12].upper()
        day = (row["created_at"] or "")[:10].replace("-", "") or "HISTORY"
        number = f"ABN-{day}-{compact_id}"
        actor_name = row["inspector_name_snapshot"] or row["inspector"] or "歷史資料"
        connection.execute(sa.text("""
            INSERT INTO abnormal_cases (
                id, case_number, inspection_id, inspection_result_id, title, description,
                severity, status, assignee_name_snapshot, corrective_action, review_note,
                created_by, created_at, updated_at, version
            ) VALUES (
                :id, :number, :inspection_id, :result_id, :title, :description,
                'normal', 'pending', '', '', '', :created_by, :created_at, :created_at, 1
            )
        """), {
            "id": case_id, "number": number, "inspection_id": row["inspection_id"],
            "result_id": row["result_id"], "title": f"{row['item_name_snapshot']}異常",
            "description": row["note"] or "", "created_by": row["inspector_user_id"],
            "created_at": row["created_at"],
        })
        connection.execute(sa.text("""
            INSERT INTO abnormal_case_histories (
                id, case_id, actor_user_id, actor_name_snapshot, action,
                from_status, to_status, note, created_at
            ) VALUES (
                :id, :case_id, :actor_id, :actor_name, 'created',
                NULL, 'pending', :note, :created_at
            )
        """), {
            "id": str(uuid4()), "case_id": case_id, "actor_id": row["inspector_user_id"],
            "actor_name": actor_name, "note": row["note"] or "", "created_at": row["created_at"],
        })


def downgrade() -> None:
    op.drop_index("ix_abnormal_attachments_case_stage", table_name="abnormal_case_attachments")
    op.drop_table("abnormal_case_attachments")
    op.drop_index("ix_abnormal_history_case_created", table_name="abnormal_case_histories")
    op.drop_table("abnormal_case_histories")
    op.drop_index("ix_abnormal_cases_assignee_status", table_name="abnormal_cases")
    op.drop_index("ix_abnormal_cases_status_due", table_name="abnormal_cases")
    op.drop_table("abnormal_cases")
