"""add article tags

新增文章标签表 ``tags`` 与复合主键关联表 ``article_tag``，供博客/文章页按标签聚合。

Revision ID: 9f8e7d6c5b4a
Revises: b2c3d4e5f607
Create Date: 2026-08-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9f8e7d6c5b4a"
down_revision: str | Sequence[str] | None = "b2c3d4e5f607"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "article_tag",
        sa.Column(
            "article_id", sa.Integer(), sa.ForeignKey("articles.id"), primary_key=True
        ),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("article_tag")
    op.drop_table("tags")
