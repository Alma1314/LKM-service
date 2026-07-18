from enum import StrEnum


class ColumnApplicationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ColumnStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ColumnPostStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


COLUMN_TABLE_PLAN = {
    "column_applications": [
        "id",
        "user_id",
        "title",
        "description",
        "reason",
        "status",
        "reviewer_id",
        "review_note",
        "created_at",
        "reviewed_at",
    ],
    "columns": [
        "id",
        "owner_id",
        "title",
        "description",
        "cover_url",
        "status",
        "created_at",
        "updated_at",
    ],
    "column_posts": [
        "id",
        "column_id",
        "author_id",
        "title",
        "summary",
        "content",
        "status",
        "created_at",
        "updated_at",
        "published_at",
    ],
}
