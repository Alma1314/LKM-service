"""HTTP-level route tests for onboarding + by-username endpoints (client fixture).

Verifies the routers are actually mounted under /api/v1 and behave end-to-end:
- GET  /api/v1/auth/onboarding
- PUT  /api/v1/auth/onboarding/steps/{step}
- POST /api/v1/auth/onboarding/skip
- GET  /api/v1/auth/user/by-username/{username} (public, no auth)
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Profile, User
from app.modules.auth.security import create_access_token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_user(db: AsyncSession, username: str) -> User:
    user = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password="x",
        account_level="normal",
    )
    db.add(user)
    await db.flush()
    db.add(Profile(user_id=user.id, role="member"))
    await db.flush()
    return user


async def _token(db: AsyncSession, user_id: int) -> str:
    return create_access_token(user_id=user_id, account_level="normal", role="member")


class TestOnboardingHTTP:
    async def test_default_and_put_and_get(self, client: Any, db: AsyncSession):
        user = await _create_user(db, "onbhttp")
        token = await _token(db, user.id)

        # default
        r = await client.get("/api/v1/auth/onboarding", headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["data"] == {"step": 1, "completed": False, "data": None}

        # put a step
        r = await client.put(
            "/api/v1/auth/onboarding/steps/1",
            headers=_auth(token),
            json={"data": {"grade": "math"}},
        )
        assert r.status_code == 200
        assert r.json()["data"]["data"] == {"1": {"grade": "math"}}

        # read back
        r = await client.get("/api/v1/auth/onboarding", headers=_auth(token))
        assert r.json()["data"]["step"] == 1

    async def test_skip_marks_completed(self, client: Any, db: AsyncSession):
        user = await _create_user(db, "onbskip")
        token = await _token(db, user.id)
        r = await client.post("/api/v1/auth/onboarding/skip", headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["data"]["completed"] is True
        assert r.json()["data"]["step"] == 4

    async def test_requires_auth(self, client: Any):
        r = await client.get("/api/v1/auth/onboarding")
        assert r.status_code in (400, 401, 403)


class TestByUsernameHTTP:
    async def test_public_lookup(self, client: Any, db: AsyncSession):
        await _create_user(db, "alice_pub")
        # no Authorization header → public access
        r = await client.get("/api/v1/auth/user/by-username/alice_pub")
        assert r.status_code == 200
        assert r.json()["data"]["nickname"] is None

    async def test_unknown_user_errors(self, client: Any):
        # USER_NOT_FOUND 按项目错误表映射为 401（前端任一错误即回退默认卡）
        r = await client.get("/api/v1/auth/user/by-username/does_not_exist")
        assert r.status_code == 401
