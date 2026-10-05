"""add four roles, user management, sessions and audit logs

Revision ID: 31b8d5a7e2f4
Revises: 8c1f42a9b0d3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "31b8d5a7e2f4"
down_revision: Union[str, None] = "8c1f42a9b0d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 先轉換舊角色；暫時略過舊 CHECK，隨後以新限制重建 users。
    op.execute("PRAGMA ignore_check_constraints = ON")
    op.execute("UPDATE users SET role = 'system_admin' WHERE role = 'admin'")
    with op.batch_alter_table("users", recreate="always") as batch:
        batch.drop_constraint("valid_user_role", type_="check")
        batch.alter_column("role", type_=sa.String(length=24), existing_type=sa.String(length=20))
        batch.add_column(sa.Column("department", sa.String(length=100), nullable=False, server_default=""))
        batch.add_column(sa.Column("email", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("locked_until", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("created_by", sa.String(length=36), nullable=True))
        batch.create_foreign_key("fk_users_created_by", "users", ["created_by"], ["id"], ondelete="SET NULL")
        batch.create_check_constraint(
            "valid_user_role",
            "role IN ('system_admin', 'inspection_manager', 'inspector', 'viewer')",
        )
    op.execute("PRAGMA ignore_check_constraints = OFF")

    with op.batch_alter_table("inspections") as batch:
        batch.add_column(sa.Column("inspector_user_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("inspector_name_snapshot", sa.String(length=100), nullable=False, server_default=""))
        batch.create_foreign_key("fk_inspections_inspector_user", "users", ["inspector_user_id"], ["id"], ondelete="SET NULL")
    op.execute("UPDATE inspections SET inspector_name_snapshot = inspector WHERE inspector_name_snapshot = ''")

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.String(length=32), nullable=False),
        sa.Column("last_seen_at", sa.String(length=32), nullable=False),
        sa.Column("revoked_at", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_user_sessions_user_active", "user_sessions", ["user_id", "revoked_at", "expires_at"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("username_snapshot", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=80), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_created", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_user_sessions_user_active", table_name="user_sessions")
    op.drop_table("user_sessions")
    with op.batch_alter_table("inspections") as batch:
        batch.drop_constraint("fk_inspections_inspector_user", type_="foreignkey")
        batch.drop_column("inspector_name_snapshot")
        batch.drop_column("inspector_user_id")
    op.execute("PRAGMA ignore_check_constraints = ON")
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'system_admin'")
    op.execute("UPDATE users SET role = 'inspector' WHERE role IN ('inspection_manager', 'viewer')")
    with op.batch_alter_table("users", recreate="always") as batch:
        batch.drop_constraint("valid_user_role", type_="check")
        batch.drop_constraint("fk_users_created_by", type_="foreignkey")
        batch.drop_column("created_by")
        batch.drop_column("locked_until")
        batch.drop_column("failed_login_count")
        batch.drop_column("must_change_password")
        batch.drop_column("email")
        batch.drop_column("department")
        batch.alter_column("role", type_=sa.String(length=20), existing_type=sa.String(length=24))
        batch.create_check_constraint("valid_user_role", "role IN ('admin', 'inspector')")
    op.execute("PRAGMA ignore_check_constraints = OFF")
