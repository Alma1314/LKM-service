"""columns: add display fields + slug

为 columns / column_posts 增加前端社区「专栏」页富展示所需字段：

- columns 新增 ``slug``（唯一，供前端按 slug 定位）、``author_name``、
  ``author_title``、``author_bio``、``avatar_url``、``is_verified``、
  ``follower_count``、``like_count``、``subscribe_count``、``article_count``、
  ``tags``、``badges``、``board_tag``。
- column_posts 新增 ``cover_image``、``view_count``、``like_count``、
  ``comment_count``。

纯新增列，跨 SQLite / PostgreSQL 安全（slug 唯一索引用 batch 模式兼容 SQLite）。

Revision ID: a1b2c3d4e5f6
Revises: e7f2a9b3c1d5
Create Date: 2026-08-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "e7f2a9b3c1d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("columns") as batch_op:
        batch_op.add_column(sa.Column("slug", sa.String(120), nullable=True))
        batch_op.add_column(sa.Column("author_name", sa.String(80), nullable=True))
        batch_op.add_column(sa.Column("author_title", sa.String(80), nullable=True))
        batch_op.add_column(sa.Column("author_bio", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("avatar_url", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column(
                "follower_count", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(
            sa.Column("like_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column(
                "subscribe_count", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(
            sa.Column(
                "article_count", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(
            sa.Column("tags", sa.Text(), nullable=False, server_default="[]")
        )
        batch_op.add_column(
            sa.Column("badges", sa.Text(), nullable=False, server_default="[]")
        )
        batch_op.add_column(sa.Column("board_tag", sa.String(50), nullable=True))
        batch_op.create_unique_constraint("uq_columns_slug", ["slug"])

    op.add_column("column_posts", sa.Column("cover_image", sa.Text(), nullable=True))
    op.add_column(
        "column_posts",
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "column_posts",
        sa.Column("like_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "column_posts",
        sa.Column(
            "comment_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )


def downgrade() -> None:
    for col in (
        "comment_count",
        "like_count",
        "view_count",
        "cover_image",
    ):
        op.drop_column("column_posts", col)
    with op.batch_alter_table("columns") as batch_op:
        batch_op.drop_constraint("uq_columns_slug", type_="unique")
        for col in (
            "board_tag",
            "badges",
            "tags",
            "article_count",
            "subscribe_count",
            "like_count",
            "follower_count",
            "is_verified",
            "avatar_url",
            "author_bio",
            "author_title",
            "author_name",
            "slug",
        ):
            batch_op.drop_column(col)
