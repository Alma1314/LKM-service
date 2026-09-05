"""add user_dim offline reporting wide table

Revision ID: f1a2e3d4c5b6a7f8
Revises: a3f5b6c7d8e9afae
Create Date: 2026-09-05

B0.1「物理建模」腿：给 auth 源加**离线**报表宽表 ``user_dim`` —— user/profile 登录锚字段的
read-only 反范式副本（单源 = auth）。此表仅供运营/报表/admin 报表读（B0.3 接线），**禁止**
任何在线读路径使用（在线一致性仍走 ``user:snap``/API）。列对齐
``app/db/user_dim.py`` UserDim（与 event_failure 同一位 —— db 层共享只读物化表，镜像其被
registry 拉进 metadata 的落位）；banned 与 ``auth.snapshot._to_snap`` 语义一致
(``banned = bool(User.is_locked)``)。

仅新增一表，绝不动 users/profiles/在线缝；可逆（downgrade 即 drop_table）。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a2e3d4c5b6a7f8"
down_revision: str | Sequence[str] | None = "a3f5b6c7d8e9afae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_dim",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("nickname", sa.String(length=100), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=True),
        sa.Column("account_level", sa.String(length=10), nullable=False),
        sa.Column("is_banned", sa.Boolean(), nullable=False),
        sa.Column("is_locked", sa.Boolean(), nullable=False),
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
        sa.Column(
            "sync_ts",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_dim"),
    )


def downgrade() -> None:
    op.drop_table("user_dim")
