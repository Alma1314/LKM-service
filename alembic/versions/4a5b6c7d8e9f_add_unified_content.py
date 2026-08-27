"""add unified content items/comments/likes tables

Revision ID: 4a5b6c7d8e9f
Revises:
Create Date: 2026-08-26

新增统一内容模型三表（content_items / content_comments / content_likes），
收敛五套旧内容表的展示语义。旧内容表（forum_posts/articles/column_posts/blog 等）
暂保留作兼容回滚，本轮仅建新表，不 drop 旧表。
"""
import sqlalchemy as sa
from alembic import op

revision = "4a5b6c7d8e9f"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("content_type", sa.String(length=20), nullable=False),
        sa.Column("board_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=True),
        sa.Column("publisher", sa.String(length=100), nullable=True),
        sa.Column("department", sa.String(length=100), nullable=True),
        sa.Column("column_id", sa.Integer(), nullable=True),
        sa.Column("qa_question_id", sa.Integer(), nullable=True),
        sa.Column("slug", sa.String(length=200), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("excerpt", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.String(length=300), nullable=True),
        sa.Column("cover", sa.Text(), nullable=True),
        sa.Column("keywords", sa.Text(), nullable=True),
        sa.Column("lang", sa.String(length=8), nullable=True),
        sa.Column("tags", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("is_pinned", sa.Boolean(), nullable=False),
        sa.Column("is_featured", sa.Boolean(), nullable=False),
        sa.Column("view_count", sa.Integer(), nullable=False),
        sa.Column("like_count", sa.Integer(), nullable=False),
        sa.Column("comment_count", sa.Integer(), nullable=False),
        sa.Column("bookmark_count", sa.Integer(), nullable=False),
        sa.Column("forward_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"]),
        sa.ForeignKeyConstraint(["column_id"], ["columns.id"]),
        sa.ForeignKeyConstraint(["qa_question_id"], ["qa_questions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_content_board_type_status",
        "content_items",
        ["board_id", "content_type", "status", "id"],
    )
    op.create_index(
        "ix_content_board_pinned", "content_items", ["board_id", "is_pinned", "id"]
    )
    op.create_index("ix_content_published", "content_items", ["published_at"])
    op.create_index("ix_content_slug", "content_items", ["slug"])

    op.create_table(
        "content_comments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("floor_number", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["content_id"], ["content_items.id"]),
        sa.ForeignKeyConstraint(["parent_id"], ["content_comments.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_content_comments_item_floor", "content_comments", ["content_id", "floor_number"]
    )

    op.create_table(
        "content_likes",
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["content_id"], ["content_items.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("content_id", "user_id"),
    )


def downgrade() -> None:
    op.drop_table("content_likes")
    op.drop_table("content_comments")
    op.drop_table("content_items")
