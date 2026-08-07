from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PostCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1)
    category_id: str = Field(..., min_length=1, max_length=50)
    tags: list[str] = Field(default_factory=list)


class PostInfo(BaseModel):
    id: int
    title: str
    excerpt: str
    content: str
    author_id: int
    author_name: str
    category_id: str
    tags: list[str]
    is_pinned: bool
    is_featured: bool
    view_count: int
    like_count: int
    comment_count: int
    bookmark_count: int
    created_at: str


class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    parent_id: int | None = Field(default=None, ge=1)


class CommentInfo(BaseModel):
    id: int
    post_id: int
    author_id: int
    author_name: str
    content: str
    floor_number: int
    parent_id: int | None = None
    like_count: int
    created_at: str


class PageData(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    pages: int
