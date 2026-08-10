from enum import StrEnum


class FileStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


FILES_TABLE_PLAN = {
    "library_files": [
        "id",
        "uploader_id",
        "original_name",
        "stored_name",
        "mime_type",
        "size",
        "category_id",
        "description",
        "tags",
        "status",
        "review_comment",
        "download_count",
        "view_count",
        "created_at",
    ],
}
