"""projects 模块：模型建表与审批流、升级、展示服务测试。"""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import BizError
from app.db.models import (
    Profile,
    Project,
    ProjectApplication,
    ProjectMember,
    User,
)
from app.modules.auth.security import create_access_token, hashpwd
from app.modules.projects.errors import ProjectErr
from app.modules.projects.schemas import (
    ProjectApplicationCreate,
    ReviewProjectApplicationRequest,
)
from app.modules.projects.service import (
    get_project,
    list_projects,
    review_application,
    submit_application,
)


async def _user(
    db: AsyncSession, username: str = "alice", level: str = "normal"
) -> int:
    u = User(
        username=username,
        email=f"{username}@e.com",
        hashed_password=await hashpwd("secret123"),
        account_level=level,
    )
    db.add(u)
    await db.flush()
    db.add(Profile(user_id=u.id, nickname=username))
    await db.flush()
    return u.id


async def test_models_can_be_created(db: AsyncSession):
    """三张新表可写可读（冒烟）。"""
    applicant = await _user(db)
    app = ProjectApplication(
        applicant_id=applicant,
        title="LKM",
        summary="s",
        description="d",
        member_claims=json.dumps([{"display_name": "艾尔", "role_in_project": "组长"}]),
        status="pending",
    )
    db.add(app)
    await db.flush()

    proj = Project(
        applicant_id=applicant,
        title="LKM",
        summary="s",
        description="d",
        is_incubated=True,
        status="active",
    )
    db.add(proj)
    await db.flush()
    db.add(
        ProjectMember(
            project_id=proj.id,
            user_id=None,
            display_name="艾尔",
            role_in_project="组长",
            sort_order=0,
        )
    )
    await db.flush()

    rows = (await db.execute(select(ProjectMember))).scalars().all()
    assert len(rows) == 1
    assert rows[0].display_name == "艾尔"


class TestProjectApplicationService:
    async def test_submit_application(self, db: AsyncSession):
        applicant = await _user(db)
        app = await submit_application(
            db,
            applicant,
            ProjectApplicationCreate(
                title="LKM",
                summary="s",
                description="d",
                member_claims=[
                    {"display_name": "艾尔", "role_in_project": "组长", "user_id": None}
                ],
            ),
        )
        assert app.status == "pending"
        assert len(app.member_claims) == 1

    async def test_duplicate_pending_rejected(self, db: AsyncSession):
        applicant = await _user(db)
        await submit_application(
            db,
            applicant,
            ProjectApplicationCreate(title="a", summary="s", description="d"),
        )
        with pytest.raises(BizError) as e:
            await submit_application(
                db,
                applicant,
                ProjectApplicationCreate(title="a", summary="s", description="d"),
            )
        assert e.value.errcode == ProjectErr.DUPLICATE_APPLICATION

    async def test_review_bad_member_user_rejected(self, db: AsyncSession):
        """member_claims 引用不存在的 user_id → 申请不落地、报错。"""
        applicant = await _user(db)
        reviewer = await _user(db, "rv", level="admin")
        app = await submit_application(
            db,
            applicant,
            ProjectApplicationCreate(
                title="a",
                summary="s",
                description="d",
                member_claims=[
                    {"display_name": "无人", "role_in_project": "r", "user_id": 99999}
                ],
            ),
        )
        with pytest.raises(BizError) as e:
            await review_application(
                db,
                app.id,
                reviewer,
                ReviewProjectApplicationRequest(approve=True),
            )
        assert e.value.errcode == ProjectErr.MEMBER_USER_NOT_FOUND
        assert await db.scalar(select(Project.id)) is None

    async def test_review_approve_creates_project_and_upgrades(self, db: AsyncSession):
        applicant = await _user(db)  # normal
        reviewer = await _user(db, "rv", level="admin")
        member_uid = await _user(db, "mem")
        app = await submit_application(
            db,
            applicant,
            ProjectApplicationCreate(
                title="LKM",
                summary="s",
                description="d",
                member_claims=[
                    {
                        "display_name": "艾尔",
                        "role_in_project": "组长",
                        "user_id": member_uid,
                    },
                    {
                        "display_name": "外援",
                        "role_in_project": "顾问",
                        "user_id": None,
                    },
                ],
            ),
        )
        out = await review_application(
            db,
            app.id,
            reviewer,
            ReviewProjectApplicationRequest(approve=True, note="ok"),
        )
        assert out.status == "approved"

        proj = await db.scalar(select(Project))
        assert proj is not None
        assert proj.is_incubated is True
        assert proj.status == "active"

        # 申请中的成员落地
        members = (
            (
                await db.execute(
                    select(ProjectMember).where(ProjectMember.project_id == proj.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(members) == 2
        by_name = {m.display_name: m for m in members}
        assert by_name["艾尔"].user_id == member_uid
        assert by_name["外援"].user_id is None

        # 申请人升级
        applicant_row = (
            (await db.execute(select(User).where(User.id == applicant)))
            .scalars()
            .first()
        )
        assert applicant_row is not None
        assert applicant_row.account_level == "admin"
        assert applicant_row.token_version >= 1
        uprof = (
            (await db.execute(select(Profile).where(Profile.user_id == applicant)))
            .scalars()
            .first()
        )
        assert uprof is not None
        assert uprof.role == "incubated_member"

    async def test_review_twice_rejected(self, db: AsyncSession):
        applicant = await _user(db)
        reviewer = await _user(db, "rv", level="admin")
        app = await submit_application(
            db,
            applicant,
            ProjectApplicationCreate(title="a", summary="s", description="d"),
        )
        await review_application(
            db, app.id, reviewer, ReviewProjectApplicationRequest(approve=True)
        )
        with pytest.raises(BizError) as e:
            await review_application(
                db, app.id, reviewer, ReviewProjectApplicationRequest(approve=True)
            )
        assert e.value.errcode == ProjectErr.APPLICATION_ALREADY_REVIEWED

    async def test_review_reject_does_not_create(self, db: AsyncSession):
        applicant = await _user(db)
        reviewer = await _user(db, "rv", level="admin")
        app = await submit_application(
            db,
            applicant,
            ProjectApplicationCreate(title="a", summary="s", description="d"),
        )
        out = await review_application(
            db,
            app.id,
            reviewer,
            ReviewProjectApplicationRequest(approve=False, note="no"),
        )
        assert out.status == "rejected"
        assert await db.scalar(select(Project.id)) is None
        applicant_row = (
            (await db.execute(select(User).where(User.id == applicant)))
            .scalars()
            .first()
        )
        assert applicant_row is not None
        assert applicant_row.account_level == "normal"  # 未升级

    async def test_upgrade_preserves_higher_role(self, db: AsyncSession):
        """已有 author 角色的申请人，孵化升级不降其角色。"""
        applicant = await _user(db)
        from sqlalchemy import update

        await db.execute(
            update(Profile).where(Profile.user_id == applicant).values(role="author")
        )
        await db.flush()
        reviewer = await _user(db, "rv", level="admin")
        app = await submit_application(
            db,
            applicant,
            ProjectApplicationCreate(title="a", summary="s", description="d"),
        )
        await review_application(
            db, app.id, reviewer, ReviewProjectApplicationRequest(approve=True)
        )
        uprof = (
            (await db.execute(select(Profile).where(Profile.user_id == applicant)))
            .scalars()
            .first()
        )
        assert uprof is not None
        assert uprof.role == "author"

    async def test_already_admin_does_not_bump_token(self, db: AsyncSession):
        """申请人已是 admin 且非 member 角色时，孵化通过不应重复递增 token_version。

        覆盖 _apply_incubation 的「无改动则不 bump」分支：account_level 不降、role 不覆盖
        更高档，故旧令牌保持有效。
        """
        applicant = await _user(db)
        from sqlalchemy import update

        await db.execute(
            update(User).where(User.id == applicant).values(account_level="admin")
        )
        await db.execute(
            update(Profile).where(Profile.user_id == applicant).values(role="author")
        )
        await db.flush()
        before_token = (
            await db.scalar(select(User.token_version).where(User.id == applicant))
        ) or 0

        reviewer = await _user(db, "rv", level="admin")
        app = await submit_application(
            db,
            applicant,
            ProjectApplicationCreate(title="a", summary="s", description="d"),
        )
        await review_application(
            db, app.id, reviewer, ReviewProjectApplicationRequest(approve=True)
        )

        after = (
            await db.scalar(select(User.token_version).where(User.id == applicant))
        ) or 0
        assert after == before_token  # 无改动则不升版本
        level = await db.scalar(select(User.account_level).where(User.id == applicant))
        assert level == "admin"  # 仍为 admin，未被降级


async def _make_approved(db: AsyncSession, username: str = "alice"):
    applicant = await _user(db, username)
    reviewer = await _user(db, f"rv_{username}", level="admin")
    app = await submit_application(
        db,
        applicant,
        ProjectApplicationCreate(
            title="P",
            summary="s",
            description="d",
            member_claims=[
                {"display_name": "艾尔", "role_in_project": "组长", "user_id": None}
            ],
        ),
    )
    await review_application(
        db, app.id, reviewer, ReviewProjectApplicationRequest(approve=True)
    )
    return applicant


class TestProjectReadService:
    async def test_list_and_detail(self, db: AsyncSession):
        await _make_approved(db)
        projects = await list_projects(db)
        assert len(projects) == 1
        assert projects[0].is_incubated is True
        assert len(projects[0].members) == 1
        detail = await get_project(db, projects[0].id)
        assert detail.title == "P"

    async def test_get_missing_raises(self, db: AsyncSession):
        with pytest.raises(BizError) as e:
            await get_project(db, 999)
        assert e.value.errcode == ProjectErr.PROJECT_NOT_FOUND


class TestProjectRoute:
    async def test_public_list(self, client, db):
        resp = await client.get("/api/v1/projects")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["items"] == []

    async def test_submit_requires_auth(self, client, db):
        # 未登录 → 403
        resp = await client.post("/api/v1/projects/applications", json={})
        assert resp.status_code == 403

        # local 用户 → 权限不足（ACCOUNT_LEVEL_INSUFFICIENT）
        locale_user = await _user(db, "loc", level="local")
        token = create_access_token(
            user_id=locale_user, account_level="local", role="member"
        )
        resp = await client.post(
            "/api/v1/projects/applications",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "t", "summary": "s", "description": "d"},
        )
        assert resp.status_code == 403

        # normal 用户可提交（RBAC 需授 projects.application_create 权限点）
        from app.db.models import RolePermission

        db.add(
            RolePermission(
                role_name="normal:member",
                permission="projects.application_create",
            )
        )
        await db.flush()
        n_user = await _user(db, "norm", level="normal")
        token = create_access_token(
            user_id=n_user, account_level="normal", role="member"
        )
        resp = await client.post(
            "/api/v1/projects/applications",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "t", "summary": "s", "description": "d"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "pending"

    async def test_review_requires_admin(self, client, db):
        n_user = await _user(db, "norm", level="normal")
        app = await submit_application(
            db,
            n_user,
            ProjectApplicationCreate(title="t", summary="s", description="d"),
        )
        token = create_access_token(
            user_id=n_user, account_level="normal", role="member"
        )
        resp = await client.post(
            f"/api/v1/projects/applications/{app.id}/review",
            headers={"Authorization": f"Bearer {token}"},
            json={"approve": True},
        )
        assert resp.status_code == 403
