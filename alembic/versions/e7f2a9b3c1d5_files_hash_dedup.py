"""files: add content-hash dedup columns

为 library_files 增加内容寻址去重所需的列：

- ``sha3_hash``：内容 SHA3-256（16 进制 64 字符），旧数据为 NULL。
- ``ref_count``：引用计数，同一物理文件被多少条目引用，DB 持久化替代内存 cache。
- ``storage_path``：物理文件落盘路径（内容寻址 ``files_store_dir/<hash>``），
  同一内容条目共享同一路径（不唯一），去重共享物理文件的关键。

保留 ``stored_name`` 的唯一约束（作展示/定位）；同一内容共享物理文件不依赖它。
SQLite 对匿名 ``UNIQUE (stored_name)`` 无法反射取名删除，故不改动该约束，仅加列，
跨 SQLite / PostgreSQL 安全。

Revision ID: e7f2a9b3c1d5
Revises: 9c7b2e4f1a3d
Create Date: 2026-08-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7f2a9b3c1d5"
down_revision: str | Sequence[str] | None = "9c7b2e4f1a3d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "library_files",
        sa.Column("sha3_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "library_files",
        sa.Column(
            "ref_count",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "library_files",
        sa.Column("storage_path", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("library_files", "storage_path")
    op.drop_column("library_files", "ref_count")
    op.drop_column("library_files", "sha3_hash")
