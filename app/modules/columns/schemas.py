from pydantic import BaseModel, Field

from app.modules.columns.models import (
    ColumnApplicationStatus,
    ColumnPostStatus,
    ColumnStatus,
)


class ColumnApplicationCreate(BaseModel):
    user_id: int
    title: str = Field(..., min_length=1, max_length=80)
    description: str = Field(..., min_length=1, max_length=300)
    reason: str = Field(..., min_length=1, max_length=500)


class ColumnApplicationInfo(BaseModel):
    id: int
    user_id: int
    title: str
    description: str
    reason: str
    status: ColumnApplicationStatus = ColumnApplicationStatus.PENDING
    reviewer_id: int | None = None
    review_note: str | None = None
    created_at: str
    reviewed_at: str | None = None


class ColumnApplicationReview(BaseModel):
    reviewer_id: int
    status: ColumnApplicationStatus
    review_note: str | None = Field(default=None, max_length=300)


class ColumnInfo(BaseModel):
    id: int
    owner_id: int
    application_id: int | None = None
    title: str
    description: str
    cover_url: str | None = None
    status: ColumnStatus = ColumnStatus.ACTIVE
    created_at: str
    updated_at: str


class ColumnPostCreate(BaseModel):
    author_id: int
    title: str = Field(..., min_length=1, max_length=120)
    summary: str | None = Field(default=None, max_length=300)
    content: str = Field(..., min_length=1)


class ColumnPostInfo(BaseModel):
    id: int
    column_id: int
    author_id: int
    title: str
    summary: str | None = None
    status: ColumnPostStatus = ColumnPostStatus.DRAFT
    created_at: str
    updated_at: str
    published_at: str | None = None
