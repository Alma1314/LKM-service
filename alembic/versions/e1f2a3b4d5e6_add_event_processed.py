"""add event_processed idempotency table

Revision ID: e1f2a3b4d5e6
Revises: d4f5a7c9b1e2
Create Date: 2026-09-04

消费者幂等去重账本（M1.3）：handler 成功处理后按 outbox event_id（透传到消费端 payload）
落此表；重放/重投同一事件消费端查到即 ack 跳过，避免二次副作用。event_id 主键自身即唯一
约束，对齐 app/db/event_processed.py EventProcessed。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e1f2a3b4d5e6"
down_revision: str | Sequence[str] | None = "d4f5a7c9b1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_processed",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("event_id", name="pk_event_processed"),
    )
    op.create_index(
        "ix_event_processed_event_id",
        "event_processed",
        ["event_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_event_processed_event_id", table_name="event_processed")
    op.drop_table("event_processed")
