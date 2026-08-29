import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class MemberClaim(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)
    role_in_project: str = Field(..., min_length=1, max_length=100)
    user_id: int | None = None


class ProjectApplicationCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    summary: str = Field(..., min_length=1, max_length=300)
    description: str = Field(..., min_length=1, max_length=500)
    member_claims: list[MemberClaim] = Field(default_factory=list)


class ProjectApplicationOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    applicant_id: int
    title: str
    summary: str
    description: str
    status: str
    member_claims: list[dict] = Field(
        default_factory=list
    )  # 请求原样回显（存 JSON 文本）
    reviewer_id: int | None = None
    review_note: str | None = None
    created_at: datetime.datetime
    reviewed_at: datetime.datetime | None = None


class ReviewProjectApplicationRequest(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=300)


class ProjectMemberOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    user_id: int | None
    display_name: str
    role_in_project: str
    sort_order: int


class ProjectOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    title: str
    summary: str
    description: str
    applicant_id: int
    is_incubated: bool
    # 项目广场展示字段
    type: str = "showcase"
    is_recruiting: bool = False
    is_pinned: bool = False
    progress: int = 0
    background: str | None = None
    goals: str | None = None
    requirements: str | None = None
    team_intro: str | None = None
    recruiting_roles: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    reports: list[dict] = Field(default_factory=list)
    applicant_name: str = ""
    status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    members: list[ProjectMemberOut] = Field(default_factory=list)
