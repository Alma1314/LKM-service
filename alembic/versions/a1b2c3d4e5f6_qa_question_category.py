"""add qa_questions.category

Revision ID: a1b2c3d4e5f6
Revises: 9d8da69dd4c2
Create Date: 2026-08-30 00:00:00

给 QA 提问表加 category 列（help|volunteer），驱动前端 Help/Volunteer 两个 tab 分类。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: str | Sequence[str] | None = '9d8da69dd4c2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "qa_questions",
        sa.Column(
            "category", sa.String(length=20), server_default="help", nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("qa_questions", "category")
