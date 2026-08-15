import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from app.modules.columns.models import (
    ColumnApplicationStatus,
    ColumnPostStatus,
    ColumnStatus,
)


class ColumnApplicationCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)
    description: str = Field(..., min_length=1, max_length=300)
    reason: str = Field(..., min_length=1, max_length=500)


class ColumnApplicationInfo(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str
    description: str
    reason: str
    status: ColumnApplicationStatus = ColumnApplicationStatus.PENDING
    reviewer_id: int | None = None
    review_note: str | None = None
    created_at: datetime.datetime
    reviewed_at: datetime.datetime | None = None


class ColumnApplicationReview(BaseModel):
    status: ColumnApplicationStatus
    review_note: str | None = Field(default=None, max_length=300)


class ColumnInfo(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    application_id: int | None = None
    title: str
    description: str
    cover_url: str | None = None
    status: ColumnStatus = ColumnStatus.ACTIVE
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ColumnPostCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    summary: str | None = Field(default=None, max_length=300)
    content: str = Field(..., min_length=1, max_length=200_000)


class ColumnPostInfo(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    column_id: int
    author_id: int
    title: str
    summary: str | None = None
    status: ColumnPostStatus = ColumnPostStatus.DRAFT
    created_at: datetime.datetime
    updated_at: datetime.datetime
    published_at: datetime.datetime | None = None


class ReviewResultData(BaseModel):
    application: ColumnApplicationInfo
    column: ColumnInfo | None = None


class ColumnPlanData(BaseModel):
    status: str
    tables: dict[str, Any]
    next_steps: list[str]
