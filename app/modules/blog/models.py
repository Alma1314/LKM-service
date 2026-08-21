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
    "blog_content": [
        "id",
        "series_id",
        "path",
        "content",
        "sha3",
        "version",
        "created_at",
        "updated_at",
    ],
    "blog_repo_quarantine": [
        "id",
        "repo_name",
        "src_dir",
        "quarantined_at",
        "created_at",
        "updated_at",
    ],
}
