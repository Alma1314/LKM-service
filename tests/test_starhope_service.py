import datetime

import pytest
from sqlalchemy import select

from app.core.err import BizError
from app.db.models import Profile, StarHopeQuestion, User
from app.modules.auth.security import hashpwd
from app.modules.starhope.errors import StarHopeErr
from app.modules.starhope.schemas import StarHopeTombstone
from app.modules.starhope.service import pull_entity, push_entity


async def _user(db, username: str = "alice") -> int:
    user = User(username=username, email=f"{username}@x.com", hashed_password=hashpwd("secret123456"), account_level="normal")
    db.add(user)
    await db.flush()
    db.add(Profile(user_id=user.id))
    await db.flush()
    return user.id


def _q(**over) -> dict:
    base = {
        "id": "q1", "type": "single", "content": "1+1=?",
        "options": ["1", "2"], "answer": "2", "analysis": "基础",
        "tags": ["数学"], "folder_id": None, "difficulty": 1,
        "updated_at": datetime.datetime(2026, 8, 15, tzinfo=datetime.UTC),
    }
    base.update(over)
    return base


class TestStarHopeService:
    async def test_pull_empty(self, db):
        uid = await _user(db)
        data = await pull_entity(db, "questions", uid, None)
        assert data.items == []
        assert data.tombstones == []
        assert data.server_time is not None

    async def test_push_insert_then_pull(self, db):
        uid = await _user(db)
        await push_entity(db, "questions", uid, [_q()], [])
        data = await pull_entity(db, "questions", uid, None)
        assert len(data.items) == 1
        assert data.items[0]["id"] == "q1"
        assert data.items[0]["answer"] == "2"
        assert data.items[0]["options"] == ["1", "2"]
        assert data.items[0]["tags"] == ["数学"]

    async def test_push_last_write_wins_skip_stale(self, db):
        uid = await _user(db)
        await push_entity(db, "questions", uid, [_q()], [])
        stale = _q(content="旧版本", updated_at=datetime.datetime(2026, 8, 14, tzinfo=datetime.UTC))
        res = await push_entity(db, "questions", uid, [stale], [])
        assert res.synced == 0
        row = (await db.execute(select(StarHopeQuestion).where(StarHopeQuestion.id == "q1"))).scalars().one()
        assert row.content == "1+1=?"

    async def test_push_newer_overwrites(self, db):
        uid = await _user(db)
        await push_entity(db, "questions", uid, [_q()], [])
        newer = _q(content="新版本", updated_at=datetime.datetime(2026, 8, 16, tzinfo=datetime.UTC))
        await push_entity(db, "questions", uid, [newer], [])
        data = await pull_entity(db, "questions", uid, None)
        assert data.items[0]["content"] == "新版本"

    async def test_delete_tombstone_returned(self, db):
        uid = await _user(db)
        await push_entity(db, "questions", uid, [_q()], [])
        tomb = StarHopeTombstone(id="q1", deleted_at=datetime.datetime(2026, 8, 17, tzinfo=datetime.UTC))
        await push_entity(db, "questions", uid, [], [tomb])
        data = await pull_entity(db, "questions", uid, None)
        assert data.items == []
        assert len(data.tombstones) == 1
        assert data.tombstones[0].id == "q1"

    async def test_pull_since_filters(self, db):
        uid = await _user(db)
        await push_entity(db, "questions", uid, [_q(id="old", updated_at=datetime.datetime(2026, 8, 10, tzinfo=datetime.UTC))], [])
        await push_entity(db, "questions", uid, [_q(id="new", updated_at=datetime.datetime(2026, 8, 20, tzinfo=datetime.UTC))], [])
        data = await pull_entity(db, "questions", uid, datetime.datetime(2026, 8, 15, tzinfo=datetime.UTC))
        assert [i["id"] for i in data.items] == ["new"]

    async def test_invalid_entity(self, db):
        uid = await _user(db)
        with pytest.raises(BizError) as exc:
            await pull_entity(db, "nope", uid, None)
        assert exc.value.errcode == StarHopeErr.INVALID_ENTITY

    async def test_textual_answer_roundtrip(self, db):
        uid = await _user(db)
        await push_entity(db, "questions", uid, [_q(answer="北京")], [])
        data = await pull_entity(db, "questions", uid, None)
        assert data.items[0]["answer"] == "北京"

    async def test_other_user_data_isolated(self, db):
        uid_a = await _user(db, "a")
        uid_b = await _user(db, "b")
        await push_entity(db, "questions", uid_a, [_q()], [])
        data_b = await pull_entity(db, "questions", uid_b, None)
        assert data_b.items == []
