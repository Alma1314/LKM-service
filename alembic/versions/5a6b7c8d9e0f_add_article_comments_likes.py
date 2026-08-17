"""add article_comments and article_likes tables

新增文章评论表 ``article_comments``（含 ``parent_id`` 自引用支持一级回复）与点赞表
``article_likes``（``article_id``+``user_id`` 复合主键保证点赞幂等）。

Revision ID: 5a6b7c8d9e0f
Revises: 9f8e7d6c5b4a
Create Date: 2026-08-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5a6b7c8d9e0f"
down_revision: str | Sequence[str] | None = "9f8e7d6c5b4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "article_comments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "article_id", sa.Integer(), sa.ForeignKey("articles.id"), nullable=False
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "parent_id", sa.Integer(), sa.ForeignKey("article_comments.id"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "article_likes",
        sa.Column(
            "article_id", sa.Integer(), sa.ForeignKey("articles.id"), primary_key=True
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("article_likes")
    op.drop_table("article_comments")
