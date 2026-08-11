import datetime
import json
from typing import ClassVar, Generic, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")


class FileCreate(BaseModel):
    original_name: str = Field(..., min_length=1, max_length=255)
    mime_type: str = Field(default="application/octet-stream", max_length=100)
    category_id: str = Field(default="", max_length=50)
    description: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list)


class FileInfo(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    original_name: str
    uploader_id: int
    uploader_name: str = ""
    mime_type: str
    size: int
    category_id: str
    category_name: str = ""
    description: str
    tags: list[str]
    status: str
    review_comment: str | None = None
    download_count: int
    view_count: int
    created_at: datetime.datetime

    @field_validator("tags", mode="before")
    @classmethod
    def _parse_tags(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return cast(list[str], v)
        if not isinstance(v, str):
            return []
        try:
            parsed = json.loads(v)
        except (json.JSONDecodeError, TypeError):
            return []
        if isinstance(parsed, list):
            return cast(list[str], parsed)
        return []


class PageData(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    pages: int
