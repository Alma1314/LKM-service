from __future__ import annotations

import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, now_iso  # 注意 db.base 而非 db.models


class Project(Base):
    __tablename__: str = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    applicant_id: Mapped[int] = mapped_column(Integer, nullable=False)  # S5: auth user_id
    is_incubated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # ———————— 项目广场展示字段（后端扩充，供 GET /projects 展示） ————————
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="showcase"
    )  # recruiting(招募中) | showcase(展示)
    is_recruiting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    background: Mapped[str | None] = mapped_column(Text, nullable=True)
    goals: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    team_intro: Mapped[str | None] = mapped_column(Text, nullable=True)
    recruiting_roles: Mapped[list] = mapped_column(JSON, default=list)  # [str] 招募角色
    tags: Mapped[list] = mapped_column(JSON, default=list)  # [str]
    reports: Mapped[list] = mapped_column(
        JSON, default=list
    )  # [{title,content,revision,date}] 进展报告
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )  # active | archived
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )

    members: Mapped[list[ProjectMember]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectApplication(Base):
    __tablename__: str = "project_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    applicant_id: Mapped[int] = mapped_column(Integer, nullable=False)  # S5: auth user_id
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    # 贡献成员清单：JSON 文本（[{display_name, role_in_project, user_id?}]），跨驱动用 Text
    member_claims: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending|approved|rejected
    reviewer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    reviewed_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )


class ProjectMember(Base):
    __tablename__: str = "project_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # S5: auth user_id
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role_in_project: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    project: Mapped[Project] = relationship(back_populates="members")
