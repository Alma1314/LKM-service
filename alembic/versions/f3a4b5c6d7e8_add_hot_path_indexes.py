"""add hot-path indexes

模块3：为读密集热路径补索引，消减列表/评论/文章接口的排序与过滤全表扫描：
- forum_posts 按 category 过滤 + (is_pinned, id) 排序
- forum_comments 按 post 过滤 + floor 排序
- articles 按 published 倒序、category 分组

Revision ID: f3a4b5c6d7e8
Revises: 5a6b7c8d9e0f
Create Date: 2026-08-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | Sequence[str] | None = "5a6b7c8d9e0f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_forum_posts_cat_pinned_id", "forum_posts", ["category_id", "is_pinned", "id"])
    op.create_index("ix_forum_comments_post_floor", "forum_comments", ["post_id", "floor_number"])
    op.create_index("ix_articles_published", "articles", ["published"])
    op.create_index("ix_articles_category_published", "articles", ["category", "published"])


def downgrade() -> None:
    op.drop_index("ix_articles_category_published", table_name="articles")
    op.drop_index("ix_articles_published", table_name="articles")
    op.drop_index("ix_forum_comments_post_floor", table_name="forum_comments")
    op.drop_index("ix_forum_posts_cat_pinned_id", table_name="forum_posts")
