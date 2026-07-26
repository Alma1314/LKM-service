from enum import StrEnum


class BlogSeriesStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


BLOG_TABLE_PLAN = {
    "blog_series": [
        "id",
        "owner_id",
        "title",
        "description",
        "cover_url",
        "repo_name",
        "status",
        "created_at",
        "updated_at",
    ],
    "blog_stars": [
        "user_id",
        "series_id",
        "created_at",
    ],
    "blog_comments": [
        "id",
        "user_id",
        "series_id",
        "content",
        "parent_id",
        "created_at",
        "updated_at",
    ],
}
