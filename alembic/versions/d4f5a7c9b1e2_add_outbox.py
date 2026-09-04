"""add outbox_events table

Revision ID: d4f5a7c9b1e2
Revises: b2c3d4e5f60b
Create Date: 2026-09-04

事务发件箱（M1.1）：业务把待投递异步事件与自身写入同事务落库，relay 领取后投 Rabbit。
列对齐 app/db/outbox.py OutboxMessage（event_id 幂等键、状态机、指数退避 next_retry_at、
锁列 locked_* 供 M1.2 leader 采纳，本轮置空）。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4f5a7c9b1e2"
down_revision: str | Sequence[str] | None = "b2c3d4e5f60b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("routing_key", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "attempt_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "next_retry_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=64), nullable=True),
        sa.UniqueConstraint("event_id", name="uq_outbox_events_event_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    # 领取窗口扫描路径：status + next_retry_at（候选行很少），按 created 时间分区前亦生效
    op.create_index(
        "ix_outbox_scan", "outbox_events", ["status", "next_retry_at"]
    )
    op.create_index("ix_outbox_events_status", "outbox_events", ["status"])


def downgrade() -> None:
    op.drop_index("ix_outbox_events_status", table_name="outbox_events")
    op.drop_index("ix_outbox_scan", table_name="outbox_events")
    op.drop_table("outbox_events")
