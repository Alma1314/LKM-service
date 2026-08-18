import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.common import parse_tags


class PostCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=200_000)
    category_id: str = Field(..., min_length=1, max_length=50)
    tags: list[str] = Field(default_factory=list)


class PostInfo(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    title: str
    excerpt: str
    content: str
    author_id: int
    author_name: str = ""
    category_id: str
    tags: list[str]
    is_pinned: bool
    is_featured: bool
    view_count: int
    like_count: int
    comment_count: int
    bookmark_count: int
    forward_count: int = 0
    created_at: datetime.datetime

    @field_validator("tags", mode="before")
    @classmethod
    def _parse_tags(cls, v: object) -> list[str]:
        return parse_tags(v)


class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    parent_id: int | None = Field(default=None, ge=1)


class CommentInfo(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    post_id: int
    author_id: int = Field(validation_alias="user_id")
    author_name: str = ""
    content: str
    floor_number: int
    parent_id: int | None = None
    like_count: int
    created_at: datetime.datetime
