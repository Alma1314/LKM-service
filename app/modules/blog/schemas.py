from pydantic import BaseModel, Field

from app.modules.auth.schemas import ProfileInfo
from app.modules.blog.models import BlogSeriesStatus


# ---- request schemas ----


class BlogSeriesCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    cover_url: str | None = None
    repo_name: str = Field(..., min_length=1, max_length=100)


class BlogSeriesUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    cover_url: str | None = None
    status: BlogSeriesStatus | None = None


class BlogCommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    parent_id: int | None = None


# ---- response schemas ----


class BlogStarStatus(BaseModel):
    starred: bool
    star_count: int


class BlogSeriesInfo(BaseModel):
    id: int
    owner_id: int
    title: str
    description: str | None = None
    cover_url: str | None = None
    repo_name: str
    status: BlogSeriesStatus = BlogSeriesStatus.ACTIVE
    created_at: str
    updated_at: str
    star_count: int = 0
    is_starred: bool = False


class BlogSeriesDetail(BaseModel):
    id: int
    owner_id: int
    title: str
    description: str | None = None
    cover_url: str | None = None
    repo_name: str
    status: BlogSeriesStatus = BlogSeriesStatus.ACTIVE
    created_at: str
    updated_at: str
    star_count: int = 0
    is_starred: bool = False
    file_tree: list[dict] | None = None


class BlogCommentInfo(BaseModel):
    id: int
    user_id: int
    series_id: int
    content: str
    parent_id: int | None = None
    created_at: str
    updated_at: str
    profile: ProfileInfo | None = None
    replies: list["BlogCommentInfo"] = []


BlogCommentInfo.model_rebuild()


class GitFileContent(BaseModel):
    filepath: str
    content: str
