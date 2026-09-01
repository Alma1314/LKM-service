from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# 以下是为user请求头校验新增的导入
from app.core.err import BizError, CommonErr
from app.modules.auth.errors import AuthErr
from app.modules.auth.security import create_access_token, hashpwd
from app.modules.content.column_models import ColumnApplicationStatus
from app.modules.content.columns.errors import ColumnErr
from app.modules.content.columns.schemas import (
    ColumnApplicationCreate,
    ColumnApplicationInfo,
    ColumnApplicationReview,
    ColumnPostCreate,
    ColumnPostInfo,
)
from app.modules.content.columns.service import (
    create_application,
    create_post,
    get_application,
    get_column,
    get_post,
    list_applications,
    list_columns,
    list_posts,
    review_application,
)

# db 与 client fixture 均由 tests/conftest.py 提供（内存 sqlite 会话 + httpx.AsyncClient）


async def _user(
    db: AsyncSession, username: str = "alice", email: str = "alice@example.com"
) -> int:
    from app.modules.auth.models import Profile, User

    user = User(
        username=username,
        email=email,
        hashed_password=await hashpwd("secret123456"),
        account_level="normal",
    )
    db.add(user)
    await db.flush()
    db.add(Profile(user_id=user.id))
    await db.flush()
    return user.id


async def _application(db: AsyncSession, user_id: int = 1) -> ColumnApplicationInfo:
    return await create_application(
        db,
        user_id,
        ColumnApplicationCreate(
            title="数学思维训练",
            description="面向高中生的数学思维和解题方法专栏。",
            reason="希望长期整理数学学习笔记。",
        ),
    )


async def _approved_column(db: AsyncSession, user_id: int = 1) -> dict[str, Any]:
    application = await _application(db, user_id=user_id)
    result: dict[str, Any] = await review_application(
        db,
        application.id,
        ColumnApplicationReview(
            status=ColumnApplicationStatus.APPROVED,
            review_note="方向明确，允许开设。",
        ),
        user_id,
    )
    return result["column"]


async def _post(
    db: AsyncSession, column_id: int = 1, author_id: int = 1
) -> ColumnPostInfo:
    return await create_post(
        db,
        column_id,
        ColumnPostCreate(
            title="如何建立函数思想",
            summary="从变量关系和图像理解入门函数思想。",
            content="函数思想的核心，是用变化关系理解问题。",
        ),
        author_id,
    )


class TestColumnApplications:
    async def should_create_application(self, db: AsyncSession):
        user_id = await _user(db)

        application = await _application(db, user_id=user_id)

        assert application.id == 1
        assert application.user_id == user_id
        assert application.status == ColumnApplicationStatus.PENDING

    async def should_list_applications(self, db: AsyncSession):
        user_id = await _user(db)
        await _application(db, user_id=user_id)

        applications = await list_applications(db)

        assert applications.total == 1
        assert applications.items[0].title == "数学思维训练"

    async def should_get_application(self, db: AsyncSession):
        user_id = await _user(db)
        application = await _application(db, user_id=user_id)

        found = await get_application(db, application.id)

        assert found.id == application.id

    async def should_reject_nonexistent_application(self, db: AsyncSession):
        with pytest.raises(BizError) as exc:
            await get_application(db, 999)

        assert exc.value.errcode == ColumnErr.APPLICATION_NOT_FOUND


class TestColumnReview:
    async def should_create_column_when_application_is_approved(self, db: AsyncSession):
        user_id = await _user(db)
        application = await _application(db, user_id=user_id)

        result: dict[str, Any] = await review_application(
            db,
            application.id,
            ColumnApplicationReview(status=ColumnApplicationStatus.APPROVED),
            user_id,
        )

        assert result["application"]["status"] == ColumnApplicationStatus.APPROVED
        assert result["column"]["id"] == 1
        assert result["column"]["owner_id"] == user_id
        assert result["column"]["application_id"] == application.id

    async def should_not_create_column_when_application_is_rejected(
        self, db: AsyncSession
    ):
        user_id = await _user(db)
        application = await _application(db, user_id=user_id)

        result: dict[str, Any] = await review_application(
            db,
            application.id,
            ColumnApplicationReview(
                status=ColumnApplicationStatus.REJECTED,
                review_note="内容方向还不够清晰。",
            ),
            user_id,
        )

        assert result["application"]["status"] == ColumnApplicationStatus.REJECTED
        assert result["column"] is None
        assert (await list_columns(db)).items == []

    async def should_reject_reviewing_already_reviewed_application(
        self, db: AsyncSession
    ):
        user_id = await _user(db)
        application = await _application(db, user_id=user_id)
        review = ColumnApplicationReview(status=ColumnApplicationStatus.APPROVED)

        await review_application(db, application.id, review, user_id)

        with pytest.raises(BizError) as exc:
            await review_application(db, application.id, review, user_id)

        assert exc.value.errcode == ColumnErr.APPLICATION_ALREADY_REVIEWED


class TestColumns:
    async def should_list_columns(self, db: AsyncSession):
        user_id = await _user(db)
        await _approved_column(db, user_id=user_id)

        columns = await list_columns(db)

        assert columns.total == 1
        assert columns.items[0].title == "数学思维训练"

    async def should_get_column(self, db: AsyncSession):
        user_id = await _user(db)
        column = await _approved_column(db, user_id=user_id)

        found = await get_column(db, column["id"])

        assert found.id == column["id"]

    async def should_reject_nonexistent_column(self, db: AsyncSession):
        with pytest.raises(BizError) as exc:
            await get_column(db, 999)

        assert exc.value.errcode == ColumnErr.NOT_FOUND


class TestColumnPosts:
    async def should_create_post(self, db: AsyncSession):
        user_id = await _user(db)
        column = await _approved_column(db, user_id=user_id)

        post = await _post(db, column_id=column["id"], author_id=user_id)

        assert post.id == 1
        assert post.column_id == column["id"]
        assert post.author_id == user_id
        assert post.status == "published"

    async def should_list_posts_under_column(self, db: AsyncSession):
        user_id = await _user(db)
        column = await _approved_column(db, user_id=user_id)
        await _post(db, column_id=column["id"], author_id=user_id)

        posts = await list_posts(db, column["id"])

        assert posts.total == 1
        assert posts.items[0].title == "如何建立函数思想"

    async def should_get_post_with_column_scope(self, db: AsyncSession):
        user_id = await _user(db)
        column = await _approved_column(db, user_id=user_id)
        post = await _post(db, column_id=column["id"], author_id=user_id)

        found = await get_post(db, post.id, column_id=column["id"])

        assert found.id == post.id

    async def should_reject_post_from_wrong_column_scope(self, db: AsyncSession):
        user_id = await _user(db)
        column = await _approved_column(db, user_id=user_id)
        post = await _post(db, column_id=column["id"], author_id=user_id)

        with pytest.raises(BizError) as exc:
            await get_post(db, post.id, column_id=999)

        assert exc.value.errcode == ColumnErr.POST_NOT_FOUND

    async def should_reject_post_for_nonexistent_column(self, db: AsyncSession):
        user_id = await _user(db)

        with pytest.raises(BizError) as exc:
            await _post(db, column_id=999, author_id=user_id)

        assert exc.value.errcode == ColumnErr.NOT_FOUND


class TestColumnRoutes:
    async def _setup_user(self, db: AsyncSession) -> tuple[int, str]:
        """Create a user in DB and return (user_id, bearer_token)."""
        from app.modules.admin.models import RolePermission

        # RBAC 迁移后写操作需权限点：为 normal:member 授 columns.application_create，
        # 与生产 DEFAULT_GRANTS seed 一致，确保「本人可申请」类用例在权限校验下通过。
        db.add(
            RolePermission(
                role_name="normal:member", permission="columns.application_create"
            )
        )
        await db.flush()
        user_id = await _user(db, username="testuser", email="test@example.com")
        token = create_access_token(
            user_id=user_id, account_level="normal", role="member"
        )
        return user_id, token

    async def should_reject_application_without_auth_header(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        await self._setup_user(db)
        application_data: dict[str, Any] = {
            "title": "数学思维训练",
            "description": "面向高中生的数学思维和解题方法专栏。",
            "reason": "希望长期整理数学学习笔记。",
        }

        response = await client.post(
            "/api/v1/content/columns/applications", json=application_data
        )

        assert response.status_code == 403
        assert response.json()["code"] == CommonErr.FORBIDDEN

    async def should_accept_application_when_token_user_matches_body_user(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        user_id, token = await self._setup_user(db)
        resp = await client.post(
            "/api/v1/content/columns/applications",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": "数学专栏",
                "description": "整理数学学习内容。",
                "reason": "长期输出学习笔记。",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["user_id"] == user_id

    async def should_reject_applications_list_for_non_admin(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        _, token = await self._setup_user(db)
        resp = await client.get(
            "/api/v1/content/columns/applications",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        assert resp.json()["code"] == AuthErr.ACCOUNT_LEVEL_INSUFFICIENT

    async def should_reject_review_for_non_admin(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        # review 走后台 cookie 会话（require_admin_2fa）：普通用户无 admin cookie → FORBIDDEN，
        # 而非旧前台 RequireLevel(admin) 的 ACCOUNT_LEVEL_INSUFFICIENT。与 boards/projects 审核一致。
        user_id, _ = await self._setup_user(db)
        await _application(db, user_id=user_id)
        resp = await client.post(
            "/api/v1/content/columns/applications/1/review",
            json={"status": "approved"},
        )
        assert resp.status_code == 403
        assert resp.json()["code"] == CommonErr.FORBIDDEN

    async def should_reject_post_for_non_owner(
        self, client: AsyncClient, db: AsyncSession
    ) -> None:
        owner_id, _ = await self._setup_user(db)
        column = await _approved_column(db, user_id=owner_id)
        intruder_id = await _user(db, username="intruder", email="intruder@example.com")
        token = create_access_token(
            user_id=intruder_id, account_level="normal", role="member"
        )
        resp = await client.post(
            f"/api/v1/content/columns/{column['id']}/posts",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "越权帖", "content": "x"},
        )
        assert resp.status_code == 403
        assert resp.json()["code"] == CommonErr.FORBIDDEN


def should_test():
    pass
