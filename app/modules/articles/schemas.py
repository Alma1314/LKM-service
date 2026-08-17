import datetime
from typing import ClassVar, cast

from pydantic import BaseModel, ConfigDict, field_validator

from app.modules.auth.schemas import ProfileInfo


class ArticleListItem(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    slug: str
    title: str
    description: str | None = None
    cover: str | None = None
    category: str
    published: datetime.datetime
    views: int = 0
    likes: int = 0
    comments: int = 0


class ArticleDetail(ArticleListItem):
    bookmarks: int = 0
    department: str | None = None
    publisher: str | None = None
    content: str
    reading_time: int = 0
    keywords: list[str] = []
    tags: list[str] = []

    @field_validator("keywords", mode="before")
    @classmethod
    def _split_keywords(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [k.strip() for k in v.split(",") if k.strip()]
        if isinstance(v, list):
            return cast(list[str], v)
        return []


class TagItem(BaseModel):
    name: str
    article_count: int


class AboutItem(BaseModel):
    title: str
    description: str
    maintainer: str


class ArticleCategory(BaseModel):
    slug: str
    name: str
    article_count: int


class ArticleListData(BaseModel):
    items: list[ArticleListItem]
    total: int


class ArticleLikeStatus(BaseModel):
    liked: bool
    like_count: int


class ArticleCommentCreate(BaseModel):
    content: str
    parent_id: int | None = None


class ArticleCommentOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    article_id: int
    user_id: int
    content: str
    parent_id: int | None = None
    created_at: datetime.datetime
    profile: ProfileInfo | None = None
