"""项目广场服务：孵化申请、审核（通过→建项目+落成员+纳入成员升级）、公开展示。"""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.err import BizError
from app.db.base import now_iso
from app.db.repo import get_or_raise
from app.modules.auth.models import Profile, User
from app.modules.projects.errors import ProjectErr
from app.modules.projects.models import Project, ProjectApplication, ProjectMember
from app.modules.projects.schemas import (
    ProjectApplicationCreate,
    ProjectApplicationOut,
    ProjectMemberOut,
    ProjectOut,
    ReviewProjectApplicationRequest,
)


def _app_to_schema(a: ProjectApplication) -> ProjectApplicationOut:
    # member_claims 在 DB 是 JSON 文本列，需显式解析（同 exam.QuestionOut.from_model 的
    # options 坑）：不能用 model_validate 自动转换，会把字符串塞进 list 报错。
    # 显式构造，先解析 JSON 再喂给 schema 的 list[dict] 字段。
    return ProjectApplicationOut(
        id=a.id,
        applicant_id=a.applicant_id,
        title=a.title,
        summary=a.summary,
        description=a.description,
        status=a.status,
        member_claims=json.loads(a.member_claims or "[]"),
        reviewer_id=a.reviewer_id,
        review_note=a.review_note,
        created_at=a.created_at,
        reviewed_at=a.reviewed_at,
    )


def _user_display(u: User) -> str:
    if u is None:
        return ""
    if u.profile and u.profile.nickname:
        return u.profile.nickname
    return u.username


def _project_to_schema(p: Project) -> ProjectOut:
    out = ProjectOut.model_validate(p)
    out.members = [ProjectMemberOut.model_validate(m) for m in p.members]
    out.applicant_name = _user_display(p.applicant)
    return out


async def submit_application(
    db: AsyncSession, applicant_id: int, info: ProjectApplicationCreate
) -> ProjectApplicationOut:
    # 同一申请人同名的 pending 申请唯一性（防重复刷单）
    dup = await db.scalar(
        select(ProjectApplication.id).where(
            ProjectApplication.applicant_id == applicant_id,
            ProjectApplication.status == "pending",
            ProjectApplication.title == info.title,
        )
    )
    if dup is not None:
        raise BizError(ProjectErr.DUPLICATE_APPLICATION)
    app_ = ProjectApplication(
        applicant_id=applicant_id,
        title=info.title,
        summary=info.summary,
        description=info.description,
        member_claims=json.dumps(
            [m.model_dump() for m in info.member_claims], ensure_ascii=False
        ),
        status="pending",
    )
    db.add(app_)
    await db.flush()
    return _app_to_schema(app_)


async def _assert_member_users_exist(db: AsyncSession, user_ids: set[int]) -> None:
    """给定的 member user_ids 必须是存在的用户。

    只在“通过审核”时（review_application 的 approve 路径）校验：提交阶段不拦截，
    待审申请可引用尚未注册的受邀账号，审核时再决定。遵循任务测试契约
    test_review_bad_member_user_rejected：提交不报错、审核时才报 MEMBER_USER_NOT_FOUND。
    """
    if not user_ids:
        return
    found = (
        (await db.execute(select(User.id).where(User.id.in_(user_ids)))).scalars().all()
    )
    missing = user_ids - set(found)
    if missing:
        raise BizError(ProjectErr.MEMBER_USER_NOT_FOUND)


async def review_application(
    db: AsyncSession,
    application_id: int,
    reviewer_id: int,
    body: ReviewProjectApplicationRequest,
) -> ProjectApplicationOut:
    app_ = await get_or_raise(
        db,
        ProjectApplication,
        ProjectErr.APPLICATION_NOT_FOUND,
        ProjectApplication.id == application_id,
    )
    if app_.status != "pending":
        raise BizError(ProjectErr.APPLICATION_ALREADY_REVIEWED)

    # 通过审核前先校验贡献成员 user 均存在；若不存在则提前报错、申请保持 pending
    # （与 boards.review_application 在修改状态前核对 slug 冲突的做法一致）。
    if body.approve:
        claims = json.loads(app_.member_claims or "[]")
        await _assert_member_users_exist(
            db,
            {c["user_id"] for c in claims if isinstance(c.get("user_id"), int)},
        )
    else:
        claims = []

    app_.reviewer_id = reviewer_id
    app_.review_note = body.note
    app_.reviewed_at = now_iso()
    app_.status = "approved" if body.approve else "rejected"
    await db.flush()

    if body.approve:
        # 落 Project
        project = Project(
            applicant_id=app_.applicant_id,
            title=app_.title,
            summary=app_.summary,
            description=app_.description,
            is_incubated=True,
            status="active",
        )
        db.add(project)
        await db.flush()
        # 落成员（含非注册成员：user_id=None）
        for i, c in enumerate(claims):
            uid = c.get("user_id")
            db.add(
                ProjectMember(
                    project_id=project.id,
                    user_id=uid if isinstance(uid, int) else None,
                    display_name=str(c.get("display_name", "")),
                    role_in_project=str(c.get("role_in_project", "")),
                    sort_order=i,
                )
            )
        await _apply_incubation(db, app_.applicant_id)
        await db.flush()
    return _app_to_schema(app_)


async def _apply_incubation(db: AsyncSession, applicant_id: int) -> None:
    """纳入成员升级：account_level 单向升 admin；role 仅在 member 档时设为 incubated_member。

    复用 exam._apply_unlock 思路：只单向提升、不降级；有改动才 token_version+1 使旧令牌失效。
    """
    from sqlalchemy import update as sa_update

    current_level = await db.scalar(
        select(User.account_level).where(User.id == applicant_id)
    )
    needs_bump = False
    if current_level != "admin":
        await db.execute(
            sa_update(User).where(User.id == applicant_id).values(account_level="admin")
        )
        needs_bump = True

    profile = await db.scalar(select(Profile).where(Profile.user_id == applicant_id))
    current_role = profile.role if profile else "member"
    if current_role in ("member", ""):
        await db.execute(
            sa_update(Profile)
            .where(Profile.user_id == applicant_id)
            .values(role="incubated_member")
        )
        needs_bump = True

    if needs_bump:
        await db.execute(
            sa_update(User)
            .where(User.id == applicant_id)
            .values(token_version=User.token_version + 1)
        )
    await db.flush()


def _project_options() -> tuple[Any, ...]:
    """成员 + 申请人（含昵称）预加载，避免 async 会话里 lazy 访问。"""
    return (
        selectinload(Project.members),
        selectinload(Project.applicant).selectinload(User.profile),
    )


async def list_projects(db: AsyncSession) -> list[ProjectOut]:
    rows = (
        (
            await db.execute(
                select(Project)
                .options(*_project_options())
                .where(Project.status == "active")
                .order_by(Project.is_pinned.desc(), Project.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_project_to_schema(p) for p in rows]


async def get_project(db: AsyncSession, project_id: int) -> Project:
    return await get_or_raise(
        db,
        Project,
        ProjectErr.PROJECT_NOT_FOUND,
        Project.id == project_id,
        options=_project_options(),
    )


async def get_project_ex(db: AsyncSession, project_id: int) -> ProjectOut:
    return _project_to_schema(await get_project(db, project_id))
