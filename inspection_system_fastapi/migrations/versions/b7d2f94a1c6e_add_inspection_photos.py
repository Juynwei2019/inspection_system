"""add inspection result photo attachments

Revision ID: b7d2f94a1c6e
Revises: 31b8d5a7e2f4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7d2f94a1c6e"
down_revision: Union[str, None] = "31b8d5a7e2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inspection_result_attachments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("inspection_result_id", sa.String(length=36), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("stored_name", sa.String(length=80), nullable=False),
        sa.Column("mime_type", sa.String(length=50), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["inspection_result_id"], ["inspection_results.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stored_name"),
    )
    op.create_index("ix_result_attachments_result", "inspection_result_attachments",
                    ["inspection_result_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_result_attachments_result", table_name="inspection_result_attachments")
    op.drop_table("inspection_result_attachments")
