from app.core.err import CommonErr
from app.db.models import Profile, User
from app.modules.auth.security import create_access_token, hashpwd


async def _setup_user(db, username="tester") -> tuple[int, str]:
    user = User(username=username, email=f"{username}@x.com", hashed_password=hashpwd("secret123456"), account_level="normal")
    db.add(user)
    await db.flush()
    db.add(Profile(user_id=user.id))
    await db.flush()
    token = create_access_token(user_id=user.id, account_level="normal", role="member")
    return user.id, token


class TestStarHopeRoutes:
    async def test_pull_requires_auth(self, client, db):
        resp = await client.get("/api/v1/starhope/questions")
        assert resp.status_code == 403

    async def test_push_and_pull_roundtrip(self, client, db):
        _, token = await _setup_user(db)
        upserts = [{
            "id": "q1", "type": "single", "content": "1+1=?",
            "options": ["1", "2"], "answer": "2", "analysis": None,
            "tags": ["数学"], "folder_id": None, "difficulty": 1,
            "updated_at": "2026-08-15T00:00:00+00:00",
        }]
        resp = await client.post(
            "/api/v1/starhope/questions/sync",
            json={"upserts": upserts, "deletes": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["synced"] == 1

        resp = await client.get(
            "/api/v1/starhope/questions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["items"][0]["id"] == "q1"
        assert data["items"][0]["answer"] == "2"

    async def test_invalid_entity_returns_422(self, client, db):
        _, token = await _setup_user(db)
        resp = await client.get(
            "/api/v1/starhope/nope",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422
        assert resp.json()["code"] != CommonErr.OK
