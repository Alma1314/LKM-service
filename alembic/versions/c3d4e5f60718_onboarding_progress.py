"""add onboarding progress table

Revision ID: c3d4e5f60718
Revises: b2c3d4e5f607
Create Date: 2026-08-30 00:10:00

注册后四步引导向导的分步持久化进度（每用户一行），对齐前端 useOnboardingFlow：
data 为以步骤号为 key 的分步合并数据（如 {1: {...}, 2: {...}}）。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'c3d4e5f60718'
down_revision: str | Sequence[str] | None = 'b2c3d4e5f607'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "onboarding_progress",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("step", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "data", sa.JSON(), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "completed", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("onboarding_progress")
