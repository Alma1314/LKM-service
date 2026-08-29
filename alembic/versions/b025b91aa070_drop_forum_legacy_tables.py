"""drop forum legacy tables

Revision ID: b025b91aa070
Revises: 4a5b6c7d8e9f
Create Date: 2026-08-29 20:44:43.078441

第二期：论坛后端已迁移到统一写源 content_items（content_type == discussion）。
本轮 drop 三张遗留旧表 forum_posts / forum_comments / forum_post_likes 及其复合索引。
索引名以 db/models.py 原 ForumPost/ForumComment __table_args__ 实定义为准
（ix_forum_posts_board_pinned_id / ix_forum_comments_post_floor），if_exists 兜底。
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b025b91aa070'
down_revision: str | Sequence[str] | None = '4a5b6c7d8e9f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop forum legacy tables (moved to content_items as single write source)."""
    op.drop_index("ix_forum_posts_board_pinned_id", table_name="forum_posts", if_exists=True)
    op.drop_index("ix_forum_comments_post_floor", table_name="forum_comments", if_exists=True)
    # sqlite_autoindex_forum_post_likes_1（复合主键自增索引）随表删除自动移除。
    op.drop_table("forum_post_likes")
    op.drop_table("forum_comments")
    op.drop_table("forum_posts")


def downgrade() -> None:
    """论坛无真实数据，downgrade 不重建（回滚到空即可）。如需恢复请先建表。"""
    pass
