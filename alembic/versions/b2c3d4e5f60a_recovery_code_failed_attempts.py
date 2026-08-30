"""add recovery_codes.failed_attempts

Revision ID: b2c3d4e5f60a
Revises: c3d4e5f60718
Create Date: 2026-08-30 00:30:00

为恢复码验证增加失败计数（failed_attempts），用于限制恢复码暴力尝试（Step-up / disable
等「所有 2FA 场景」复用 verify_second_factor，之前恢复码分支无失败锁定）。新码用带 pepper
的 HMAC 存储（hash_recovery_code），存量裸 SHA-256 仍可校验（见 verification 的 legacy 兜底），
故本迁移仅加列、不重写数据。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f60a"
down_revision: str | Sequence[str] | None = "c3d4e5f60718"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recovery_codes",
        sa.Column(
            "failed_attempts", sa.Integer(), server_default="0", nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("recovery_codes", "failed_attempts")
