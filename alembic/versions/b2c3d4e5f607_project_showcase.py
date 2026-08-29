"""expand projects for showcase

Revision ID: b2c3d4e5f607
Revises: a1b2c3d4e5f6
Create Date: 2026-08-30 00:01:00

项目广场展示字段扩充：projects 表加 type/is_recruiting/is_pinned/progress、
background/goals/requirements/team_intro（长文本）及 recruiting_roles/tags/reports（JSON）。
已有存量行用 server_default 兜底，保证 upgrade 不依赖代码。
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f607'
down_revision: str | Sequence[str] | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("type", sa.String(length=20), server_default="showcase", nullable=False))
    op.add_column("projects", sa.Column("is_recruiting", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("projects", sa.Column("is_pinned", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("projects", sa.Column("progress", sa.Integer(), server_default="0", nullable=False))
    op.add_column("projects", sa.Column("background", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("goals", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("requirements", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("team_intro", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("recruiting_roles", sa.JSON(), server_default=sa.text("'[]'"), nullable=False))
    op.add_column("projects", sa.Column("tags", sa.JSON(), server_default=sa.text("'[]'"), nullable=False))
    op.add_column("projects", sa.Column("reports", sa.JSON(), server_default=sa.text("'[]'"), nullable=False))


def downgrade() -> None:
    for col in (
        "reports",
        "tags",
        "recruiting_roles",
        "team_intro",
        "requirements",
        "goals",
        "background",
        "progress",
        "is_pinned",
        "is_recruiting",
        "type",
    ):
        op.drop_column("projects", col)
