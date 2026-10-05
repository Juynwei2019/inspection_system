"""add users and authentication

Revision ID: 8c1f42a9b0d3
Revises: 6f24d9ec380d
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8c1f42a9b0d3"
down_revision: Union[str, None] = "6f24d9ec380d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.String(length=32), nullable=False),
        sa.Column("last_login_at", sa.String(length=32), nullable=True),
        sa.CheckConstraint("role IN ('admin', 'inspector')", name="valid_user_role"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )


def downgrade() -> None:
    op.drop_table("users")
