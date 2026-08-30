"""QA 模块测试：escrow 锁定/防超发/退回/状态机/权限。"""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import BizError
from app.db.models import QAQuestion, User
from app.modules.auth.security import create_access_token
from app.modules.points.service import get_balance, reward
from app.modules.content.errors import QaErr
from app.modules.content.qa_schemas import AnswerCreate, QuestionCreate
from app.modules.content.qa_service import (
    accept_answer,
    close_question,
    create_answer,
    create_question,
    get_question,
    list_questions,
)


async def _user(
    db: AsyncSession, username: str = "alice", level: str = "normal"
) -> int:
    from app.db.models import Profile
    from app.modules.auth.security import hashpwd

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


async def _asker_with_bounty(db: AsyncSession, people=2, per=30) -> tuple[int, int]:
    """建一个发问者（先给积分）+ 发一个问题。返回 (question_id, asker_id)。"""
    asker = await _user(db, "asker")
    await reward(db, asker, 1000, "seed", "seed", str(asker))
    q = await create_question(
        db,
        asker,
        QuestionCreate(
            title="题目",
            situation="情况",
            content="内容",
            bounty_people=people,
            bounty_per_person=per,
        ),
    )
    return q.id, asker


class TestAsk:
    async def test_asker_spends_escrow(self, db: AsyncSession):
        asker = await _user(db, "asker")
        await reward(db, asker, 1000, "seed", "s", "1")
        q = await create_question(
            db,
            asker,
            QuestionCreate(
                title="t",
                situation="s",
                content="c",
                bounty_people=2,
                bounty_per_person=30,
            ),
        )
        assert q.bounty_total == 60
        assert await get_balance(db, asker) == 940  # 1000-60

    async def test_create_insufficient(self, db: AsyncSession):
        from app.modules.points.errors import PointsErr

        asker = await _user(db, "poor")
        with pytest.raises(BizError) as exc:
            await create_question(
                db,
                asker,
                QuestionCreate(
                    title="t",
                    situation="s",
                    content="c",
                    bounty_people=2,
                    bounty_per_person=30,
                ),
            )
        assert exc.value.errcode == PointsErr.INSUFFICIENT_BALANCE


class TestAnswer:
    async def test_answer_flow(self, db: AsyncSession):
        qid, _asker = await _asker_with_bounty(db)
        ans = await _user(db, "answerer")
        a = await create_answer(db, qid, ans, AnswerCreate(content="我来答"))
        assert a.question_id == qid
        detail = await get_question(db, qid)
        assert detail.answer_count == 1


class TestAccept:
    async def test_accept_pays_answerer(self, db: AsyncSession):
        qid, asker = await _asker_with_bounty(db, people=2, per=30)
        answerer = await _user(db, "answerer")
        a = await create_answer(db, qid, answerer, AnswerCreate(content="答"))
        await accept_answer(db, qid, a.id, asker)
        assert await get_balance(db, answerer) == 30
        q = (
            (await db.execute(select(QAQuestion).where(QAQuestion.id == qid)))
            .scalars()
            .first()
        )
        assert q is not None and q.bounty_distributed == 30

    async def test_accept_exhausts_after_people(self, db: AsyncSession):
        qid, asker = await _asker_with_bounty(db, people=2, per=30)
        a1 = await create_answer(
            db, qid, await _user(db, "r1"), AnswerCreate(content="1")
        )
        a2 = await create_answer(
            db, qid, await _user(db, "r2"), AnswerCreate(content="2")
        )
        a3 = await create_answer(
            db, qid, await _user(db, "r3"), AnswerCreate(content="3")
        )
        await accept_answer(db, qid, a1.id, asker)
        await accept_answer(db, qid, a2.id, asker)
        with pytest.raises(BizError) as e:
            await accept_answer(db, qid, a3.id, asker)
        assert e.value.errcode == QaErr.BOUNTY_EXHAUSTED

    async def test_accept_non_asker_rejected(self, db: AsyncSession):
        qid, _asker = await _asker_with_bounty(db)
        other = await _user(db, "other")
        a = await create_answer(
            db, qid, await _user(db, "r"), AnswerCreate(content="x")
        )
        with pytest.raises(BizError) as e:
            await accept_answer(db, qid, a.id, other)
        assert e.value.errcode == QaErr.NOT_ASKER


class TestClose:
    async def test_close_refunds_remainder(self, db: AsyncSession):
        qid, asker = await _asker_with_bounty(db, people=2, per=30)
        a = await create_answer(
            db, qid, await _user(db, "r"), AnswerCreate(content="x")
        )
        await accept_answer(db, qid, a.id, asker)  # 派发 30
        # 未派发完 30 应退回 → asker 余额 = 1000-60+30 = 970
        await close_question(db, qid, asker)
        assert await get_balance(db, asker) == 970

    async def test_close_no_accepts_refunds_full(self, db: AsyncSession):
        qid, asker = await _asker_with_bounty(db, people=2, per=30)
        # 无人采纳，直接关闭 → 全退 60
        q = await close_question(db, qid, asker)
        assert await get_balance(db, asker) == 1000
        assert q.status == "closed"


class TestList:
    async def test_list_paginated(self, db: AsyncSession):
        qid, _ = await _asker_with_bounty(db)
        data = await list_questions(db, page=1, limit=10)
        assert data.total == 1
        assert data.items[0].id == qid


class TestPermission:
    async def test_local_user_cannot_post_question(
        self, client: httpx.AsyncClient, db: AsyncSession
    ):
        uid = await _user(db, "localuser", level="local")
        token = create_access_token(uid, "local", "member")
        resp = await client.post(
            "/api/v1/content/qa/questions",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": "t",
                "situation": "s",
                "content": "c",
                "bounty_people": 1,
                "bounty_per_person": 10,
            },
        )
        assert resp.status_code == 403

    async def test_list_public(self, client: httpx.AsyncClient, db: AsyncSession):
        await _asker_with_bounty(db)
        resp = await client.get("/api/v1/content/qa/questions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 1
        # 统一分页依赖自动附加 X-Total 头（与 body total 一致）
        assert resp.headers["X-Total"] == "1"


class TestQuestionForumSync:
    """QA 提问同步为论坛内容条目（content_items content_type='qa'）。"""

    async def test_create_question_syncs_content_item(self, db: AsyncSession) -> None:
        from app.db.models import ContentItem

        asker = await _user(db, "syncasker")
        q = await create_question(
            db,
            asker,
            QuestionCreate(
                title="同步题目",
                situation="情况",
                content="内容",
                bounty_people=1,
                bounty_per_person=0,
            ),
        )
        # 论坛条目已生成，指向该提问
        item = (
            (
                await db.execute(
                    select(ContentItem).where(
                        ContentItem.content_type == "qa",
                        ContentItem.qa_question_id == q.id,
                    )
                )
            )
            .scalars()
            .first()
        )
        assert item is not None
        assert item.title == "同步题目"
        assert item.author_id == asker
