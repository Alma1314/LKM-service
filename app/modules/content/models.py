from enum import StrEnum


class ContentType(StrEnum):
    """统一内容模型的内容体裁判别列。

    五套旧内容表（forum_posts / articles / column_posts / blog 发布产物）收敛为
    一张 content_items 表，用本枚举区分展示语义：
    - discussion：普通讨论帖（原 forum_posts，无审稿，发即 published）
    - article：官方发布文章（原 articles，含官方字段 publisher/department，含 news 分类）
    - column_post：专栏连载（原 column_posts，挂 column_id，追更）
    - blog_post：博客发布产物（原 blog_series 发布后落成的展示内容）
    """

    DISCUSSION = "discussion"
    ARTICLE = "article"
    COLUMN_POST = "column_post"
    BLOG_POST = "blog_post"


class ContentStatus(StrEnum):
    """content_items.status 状态机。

    各体裁对齐旧语义：
    - discussion 恒 PUBLISHED（发即公开）
    - article / column_post / blog_post 支持 draft / pending / published / rejected
    """

    DRAFT = "draft"
    PENDING = "pending"
    PUBLISHED = "published"
    REJECTED = "rejected"


CONTENT_TABLE_PLAN = {
    "content_items": [
        "id",
        "content_type",
        "board_id",
        "author_id",
        "publisher",
        "department",
        "column_id",
        "slug",
        "title",
        "excerpt",
        "content",
        "summary",
        "cover",
        "keywords",
        "lang",
        "tags",
        "status",
        "is_pinned",
        "is_featured",
        "view_count",
        "like_count",
        "comment_count",
        "bookmark_count",
        "forward_count",
        "created_at",
        "updated_at",
        "published_at",
    ],
    "content_comments": [
        "id",
        "content_id",
        "user_id",
        "content",
        "floor_number",
        "parent_id",
        "like_count",
        "created_at",
    ],
    "content_likes": [
        "content_id",
        "user_id",
        "created_at",
    ],
}
