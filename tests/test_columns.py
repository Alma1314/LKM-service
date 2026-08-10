import pytest

from app.core.err import BizError, CommonErr
from app.modules.columns.errors import ColumnErr
from app.db.models import Base, User
from app.modules.columns.models import ColumnApplicationStatus
from app.modules.columns.schemas import (
    ColumnApplicationCreate,
    ColumnApplicationReview,
    ColumnPostCreate,
)
from app.modules.columns.service import (
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
#以下是为user请求头校验新增的导入
import app.modules.auth.models  # pyright: ignore[reportUnusedImport]
from app.modules.auth.security import create_access_token, hashpwd

# db 与 client fixture 均由 tests/conftest.py 提供（内存 sqlite 会话 + httpx.AsyncClient）


async def _user(db, username="alice", email="alice@example.com"):
    from app.db.models import User, Profile
    user = User(
        username=username, email=email,
        hashed_password=hashpwd("secret123456"), account_level="normal",
    )
    db.add(user)
    await db.flush()
    db.add(Profile(user_id=user.id))
    await db.flush()
    return user.id


async def _application(db, user_id=1):
    return await create_application(
        db,
        ColumnApplicationCreate(
            user_id=user_id,
            title="数学思维训练",
            description="面向高中生的数学思维和解题方法专栏。",
            reason="希望长期整理数学学习笔记。",
        ),
    )


async def _approved_column(db, user_id=1):
    application = await _application(db, user_id=user_id)
    result = await review_application(
        db,
        application.id,
        ColumnApplicationReview(
            reviewer_id=user_id,
            status=ColumnApplicationStatus.APPROVED,
            review_note="方向明确，允许开设。",
        ),
    )
    return result["column"]


async def _post(db, column_id=1, author_id=1):
    return await create_post(
        db,
        column_id,
        ColumnPostCreate(
            author_id=author_id,
            title="如何建立函数思想",
            summary="从变量关系和图像理解入门函数思想。",
            content="函数思想的核心，是用变化关系理解问题。",
        ),
    )


class TestColumnApplications:
    async def should_create_application(self, db):
        user_id = await _user(db)

        application = await _application(db, user_id=user_id)

        assert application.id == 1
        assert application.user_id == user_id
        assert application.status == ColumnApplicationStatus.PENDING

    async def should_list_applications(self, db):
        user_id = await _user(db)
        await _application(db, user_id=user_id)

        applications = await list_applications(db)

        assert len(applications) == 1
        assert applications[0].title == "数学思维训练"

    async def should_get_application(self, db):
        user_id = await _user(db)
        application = await _application(db, user_id=user_id)

        found = await get_application(db, application.id)

        assert found.id == application.id

    async def should_reject_nonexistent_application(self, db):
        with pytest.raises(BizError) as exc:
            await get_application(db, 999)

        assert exc.value.errcode == ColumnErr.APPLICATION_NOT_FOUND


class TestColumnReview:
    async def should_create_column_when_application_is_approved(self, db):
        user_id = await _user(db)
        application = await _application(db, user_id=user_id)

        result = await review_application(
            db,
            application.id,
            ColumnApplicationReview(
                reviewer_id=user_id,
                status=ColumnApplicationStatus.APPROVED,
            ),
        )

        assert result["application"]["status"] == ColumnApplicationStatus.APPROVED
        assert result["column"]["id"] == 1
        assert result["column"]["owner_id"] == user_id
        assert result["column"]["application_id"] == application.id

    async def should_not_create_column_when_application_is_rejected(self, db):
        user_id = await _user(db)
        application = await _application(db, user_id=user_id)

        result = await review_application(
            db,
            application.id,
            ColumnApplicationReview(
                reviewer_id=user_id,
                status=ColumnApplicationStatus.REJECTED,
                review_note="内容方向还不够清晰。",
            ),
        )

        assert result["application"]["status"] == ColumnApplicationStatus.REJECTED
        assert result["column"] is None
        assert await list_columns(db) == []

    async def should_not_duplicate_column_when_approving_twice(self, db):
        user_id = await _user(db)
        application = await _application(db, user_id=user_id)
        review = ColumnApplicationReview(
            reviewer_id=user_id,
            status=ColumnApplicationStatus.APPROVED,
        )

        first = await review_application(db, application.id, review)
        second = await review_application(db, application.id, review)

        assert first["column"]["id"] == second["column"]["id"]
        assert len(await list_columns(db)) == 1


class TestColumns:
    async def should_list_columns(self, db):
        user_id = await _user(db)
        await _approved_column(db, user_id=user_id)

        columns = await list_columns(db)

        assert len(columns) == 1
        assert columns[0].title == "数学思维训练"

    async def should_get_column(self, db):
        user_id = await _user(db)
        column = await _approved_column(db, user_id=user_id)

        found = await get_column(db, column["id"])

        assert found.id == column["id"]

    async def should_reject_nonexistent_column(self, db):
        with pytest.raises(BizError) as exc:
            await get_column(db, 999)

        assert exc.value.errcode == ColumnErr.NOT_FOUND


class TestColumnPosts:
    async def should_create_post(self, db):
        user_id = await _user(db)
        column = await _approved_column(db, user_id=user_id)

        post = await _post(db, column_id=column["id"], author_id=user_id)

        assert post.id == 1
        assert post.column_id == column["id"]
        assert post.author_id == user_id
        assert post.status == "published"

    async def should_list_posts_under_column(self, db):
        user_id = await _user(db)
        column = await _approved_column(db, user_id=user_id)
        await _post(db, column_id=column["id"], author_id=user_id)

        posts = await list_posts(db, column["id"])

        assert len(posts) == 1
        assert posts[0].title == "如何建立函数思想"

    async def should_get_post_with_column_scope(self, db):
        user_id = await _user(db)
        column = await _approved_column(db, user_id=user_id)
        post = await _post(db, column_id=column["id"], author_id=user_id)

        found = await get_post(db, post.id, column_id=column["id"])

        assert found.id == post.id

    async def should_reject_post_from_wrong_column_scope(self, db):
        user_id = await _user(db)
        column = await _approved_column(db, user_id=user_id)
        post = await _post(db, column_id=column["id"], author_id=user_id)

        with pytest.raises(BizError) as exc:
            await get_post(db, post.id, column_id=999)

        assert exc.value.errcode == ColumnErr.POST_NOT_FOUND

    async def should_reject_post_for_nonexistent_column(self, db):
        user_id = await _user(db)

        with pytest.raises(BizError) as exc:
            await _post(db, column_id=999, author_id=user_id)

        assert exc.value.errcode == ColumnErr.NOT_FOUND
class TestColumnRoutes:
    async def _setup_user(self, db):
        """Create a user in DB and return (user_id, bearer_token)."""
        user_id = await _user(db, username="testuser", email="test@example.com")
        token = create_access_token(user_id=user_id, account_level="normal", role="member")
        return user_id, token

    async def should_reject_application_without_auth_header(self, client, db):
        await self._setup_user(db)
        application_data = {
            "user_id": 1,
            "title": "数学思维训练",
            "description": "面向高中生的数学思维和解题方法专栏。",
            "reason": "希望长期整理数学学习笔记。",
        }

        response = await client.post(
            "/api/v1/columns/applications",
            json=application_data)

        assert response.status_code == 403
        assert response.json()["code"] == CommonErr.FORBIDDEN

    async def should_reject_application_when_token_user_mismatches_body_user(self, client, db):
        user_id_1, token = await self._setup_user(db)
        # Create a second user so token for user_id=2 is valid
        await _user(db, username="other", email="other@example.com")
        token_2 = create_access_token(user_id=2, account_level="normal", role="member")
        resp = await client.post(
            "/api/v1/columns/applications",
            headers={"Authorization": f"Bearer {token_2}"},
            json={
                "user_id": user_id_1,
                "title": "数学专栏",
                "description": "整理数学学习内容。",
                "reason": "长期输出学习笔记。",
            },
        )

        assert resp.status_code == 403
        assert resp.json()["code"] == CommonErr.FORBIDDEN

    async def should_accept_application_when_token_user_matches_body_user(self, client, db):
        user_id, token = await self._setup_user(db)
        resp = await client.post(
            "/api/v1/columns/applications",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "user_id": user_id,
                "title": "数学专栏",
                "description": "整理数学学习内容。",
                "reason": "长期输出学习笔记。",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["user_id"] == user_id

def should_test():
    pass