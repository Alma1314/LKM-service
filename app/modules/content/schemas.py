import datetime
from typing import ClassVar, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.common import parse_tags


class ContentItemInfo(BaseModel):
    """统一内容项输出。``author_name`` 优先 user FK 的昵称，否则回退 publisher。"""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    content_type: str
    board_id: int
    author_id: int | None = None
    author_name: str = ""
    publisher: str | None = None
    department: str | None = None
    column_id: int | None = None
    column_title: str = ""
    qa_question_id: int | None = None
    slug: str | None = None
    title: str
    excerpt: str
    summary: str | None = None
    cover: str | None = None
    keywords: list[str] = []
    content: str
    tags: list[str] = []
    status: str = "published"
    is_pinned: bool = False
    is_featured: bool = False
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    bookmark_count: int = 0
    forward_count: int = 0
    reading_time: int = 0
    created_at: datetime.datetime
    published_at: datetime.datetime | None = None

    @field_validator("tags", "keywords", mode="before")
    @classmethod
    def _parse_list(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return cast(list[str], v)
        if isinstance(v, str):
            if v.startswith("["):
                return parse_tags(v)
            return [k.strip() for k in v.split(",") if k.strip()]
        return []


class ContentItemCreate(BaseModel):
    content_type: str = Field(default="discussion")
    board_id: int = Field(..., ge=1)
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=200_000)
    summary: str | None = Field(default=None, max_length=300)
    cover: str | None = Field(default=None, max_length=2000)
    tags: list[str] = Field(default_factory=list)
    # 官方发布字段（content_type == article 时）
    slug: str | None = Field(default=None, max_length=200, pattern=r"^[a-z0-9-]+$")
    publisher: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=100)
    keywords: list[str] = Field(default_factory=list)
    # 专栏连载（content_type == column_post）
    column_id: int | None = Field(default=None, ge=1)
    # QA 提问（content_type == qa）
    qa_question_id: int | None = Field(default=None, ge=1)
    status: str = Field(default="published", pattern="^(draft|pending|published)$")
    is_pinned: bool = False
    is_featured: bool = False


class ContentCommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    parent_id: int | None = Field(default=None, ge=1)


class ContentCommentInfo(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    content_id: int
    author_id: int = Field(validation_alias="user_id")
    author_name: str = ""
    content: str
    floor_number: int
    parent_id: int | None = None
    like_count: int
    created_at: datetime.datetime
