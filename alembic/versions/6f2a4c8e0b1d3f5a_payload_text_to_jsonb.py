"""migrate event payload columns Text -> JSONB

Revision ID: 6f2a4c8e0b1d3f5a
Revises: f1a2e3d4c5b6a7f8
Create Date: 2026-09-06

S5+ 全站规范化：事件 infra 的三个「payload」列（outbox_events / event_failures /
dlq_messages 的 ``payload_json``）原先为跨库以 Text 存 json 字符串；统一纯 PostgreSQL 后
升级为原生 ``JSONB`` 存 dict。PG 侧用 ``USING payload_json::jsonb`` 原地转换既有存量内容
（数据安全——值本就是合法 JSON），模型 ORM 一并从 ``Mapped[str]`` 改为 ``Mapped[dict]``，
写/读两侧不再手动 json.dumps/loads（见对应 service）。可逆：downgrade 以 ``::text`` 转回。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "6f2a4c8e0b1d3f5a"
down_revision: str | Sequence[str] | None = "f1a2e3d4c5b6a7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (表, 列, 原 non-null)：事件 infra 的 transport payload，合法 JSON 文本 → JSONB。
# outbox_events / event_failures 均 NOT NULL；dlq_messages 许空。
_PAYLOAD_COLUMNS: list[tuple[str, str, bool]] = [
    ("outbox_events", "payload_json", True),
    ("event_failures", "payload_json", True),
    ("dlq_messages", "payload_json", False),
]


def upgrade() -> None:
    for table, col, not_null in _PAYLOAD_COLUMNS:
        op.alter_column(
            table,
            col,
            type_=postgresql.JSONB(),
            nullable=not not_null,
            existing_type=sa.Text(),
            postgresql_using=f"{col}::jsonb",
        )


def downgrade() -> None:
    for table, col, not_null in _PAYLOAD_COLUMNS:
        op.alter_column(
            table,
            col,
            type_=sa.Text(),
            nullable=not not_null,
            existing_type=postgresql.JSONB(),
            postgresql_using=f"{col}::text",
        )
