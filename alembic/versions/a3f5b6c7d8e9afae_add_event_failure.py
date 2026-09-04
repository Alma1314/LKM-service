"""add event_failures table

Revision ID: a3f5b6c7d8e9afae
Revises: e1f2a3b4d5e6
Create Date: 2026-09-04

outbox 发布耗竭归档（M1 gate review 收口）：relay `attempt_count` 达 MAX 的 outbox 行
从 outbox_events 摘除迁此表。列对齐 `app/db/event_failure.py` EventFailure（审计副本）。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3f5b6c7d8e9afae"
down_revision: str | Sequence[str] | None = "e1f2a3b4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_failures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("routing_key", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reason", sa.String(length=255), server_default="", nullable=False),
        sa.Column(
            "folded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_failures_event_id", "event_failures", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_event_failures_event_id", table_name="event_failures")
    op.drop_table("event_failures")
