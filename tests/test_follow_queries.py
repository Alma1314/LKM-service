"""follow 查询端点测试：关注状态、我关注的用户/版块列表。

覆盖：
- service 层：is_following_user / list_following_users / list_followed_boards
- HTTP：GET /users/me/following、GET /boards/me/following（均需登录）、
        GET /users/{id}/follow/status（匿名恒 False、已登录看实际状态）
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Profile, User
from app.modules.auth.security import create_access_token, hashpwd
from app.modules.follow import service as follow_service
from app.modules.follow.service import (
    is_following_user,
    list_followed_boards,
    list_following_users,
)


async def _user(db: AsyncSession, username: str, email: str) -> User:
    user = User(
        username=username,
        email=email,
        hashed_password=await hashpwd("secret123456"),
        account_level="normal",
    )
    db.add(user)
    await db.flush()
    db.add(Profile(user_id=user.id, nickname=username))
    await db.flush()
    return user


def _hdr(u: User) -> dict[str, str]:
    tok = create_access_token(
        user_id=u.id, account_level=u.account_level, role="member"
    )
    return {"Authorization": f"Bearer {tok}"}


async def _board(db: AsyncSession, slug: str) -> int:
    from app.modules.content.boards.schemas import BoardCreate
    from app.modules.content.boards.service import create_board_ex

    return (await create_board_ex(db, BoardCreate(slug=slug, title=slug), None)).id


class TestFollowService:
    async def test_is_following_user(self, db: AsyncSession) -> None:
        a = await _user(db, "alice", "alice@ex.com")
        b = await _user(db, "bob", "bob@ex.com")
        assert await is_following_user(db, a.id, b.id) is False
        await follow_service.follow_user(db, a.id, b.id)
        assert await is_following_user(db, a.id, b.id) is True
        await follow_service.unfollow_user(db, a.id, b.id)
        assert await is_following_user(db, a.id, b.id) is False

    async def test_list_following_users_returns_display_name(
        self, db: AsyncSession
    ) -> None:
        a = await _user(db, "alice", "a@ex.com")
        b = await _user(db, "bob", "b@ex.com")
        await follow_service.follow_user(db, a.id, b.id)
        rows = await list_following_users(db, a.id)
        assert [(uid, name) for uid, name, _ in rows] == [(b.id, "bob")]

    async def test_list_followed_boards(self, db: AsyncSession) -> None:
        a = await _user(db, "alice", "aa@ex.com")
        bid = await _board(db, "tech")
        await follow_service.follow_board(db, a.id, bid)
        rows = await list_followed_boards(db, a.id)
        assert rows == [(bid, "tech")]


class TestFollowHttp:
    async def test_status_anonymous_is_false(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        target = await _user(db, "target", "t@ex.com")
        resp = await client.get(f"/api/v1/users/{target.id}/follow/status")
        assert resp.status_code == 200
        assert resp.json()["data"]["is_following"] is False

    async def test_status_authenticated_reflects_follow(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        me = await _user(db, "me", "me@ex.com")
        target = await _user(db, "target", "t2@ex.com")
        await follow_service.follow_user(db, me.id, target.id)
        resp = await client.get(
            f"/api/v1/users/{target.id}/follow/status", headers=_hdr(me)
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["is_following"] is True

    async def test_following_users_list(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        me = await _user(db, "me", "m1@ex.com")
        b1 = await _user(db, "b1", "b1@ex.com")
        b2 = await _user(db, "b2", "b2@ex.com")
        await follow_service.follow_user(db, me.id, b1.id)
        await follow_service.follow_user(db, me.id, b2.id)
        resp = await client.get("/api/v1/users/me/following", headers=_hdr(me))
        assert resp.status_code == 200
        ids = {it["user_id"] for it in resp.json()["data"]["items"]}
        assert ids == {b1.id, b2.id}

    async def test_following_boards_list(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        me = await _user(db, "me", "m2@ex.com")
        bid = await _board(db, "dev")
        await follow_service.follow_board(db, me.id, bid)
        resp = await client.get("/api/v1/content/boards/me/following", headers=_hdr(me))
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert items[0]["board_id"] == bid and items[0]["title"] == "dev"

    async def test_following_requires_login(
        self, db: AsyncSession, client: AsyncClient
    ) -> None:
        resp = await client.get("/api/v1/users/me/following")
        assert resp.status_code == 403
