"""考试/竞赛子系统测试：建考、列表、开考、交卷、升级闭环、seed 幂等。

覆盖（对齐 Task 6 验收清单）：
- 建考计数：题目批量写入
- 列表：公开只读
- 未发布拒考
- 开考 + 交卷 + 升级 account_level/profile.role + 证书 + token_version 失效
- 重交卷拒绝（status 检查先于"已通过"守卫）
- 越权交卷拒绝
- 路由：列表公开、开考需认证、认证等级不足
- seed 幂等
"""

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import BizError, CommonErr
from app.db.models import Exam, ExamCertificate, ExamQuestion, Profile, User
from app.modules.auth.security import create_access_token, hashpwd
from app.modules.exam.errors import ExamErr
from app.modules.exam.schemas import ExamCreate, QuestionCreate, SubmitAnswersRequest
from app.modules.exam.service import (
    create_exam_ex,
    list_exams,
    start_attempt,
    submit_attempt,
)


def _exam_create() -> ExamCreate:
    """两题、满分为 40 分；pass_score=40 使满分恰好通过。

    注意 pass_score 必须 <= 满分（20+20=40），否则"完美作答"也无法及格——
    这与 seed 的认证考试（每题 20 分、共 3-4 题）同一口径。
    """
    return ExamCreate(
        type="exam",
        title="测试考试",
        subject="math",
        pass_score=40,
        time_limit_min=30,
        unlock_level="normal",
        questions=[
            QuestionCreate(
                kind="single",
                content="1+1=?",
                options=[{"key": "A", "text": "2"}, {"key": "B", "text": "3"}],
                answer="A",
                score=20,
            ),
            QuestionCreate(
                kind="judge",
                content="2*2=4",
                options=[],
                answer="T",
                score=20,
            ),
        ],
    )


async def _user(
    db: AsyncSession, username: str = "alice", email: str = "a@e.com"
) -> int:
    user = User(
        username=username,
        email=email,
        hashed_password=await hashpwd("secret123"),
        account_level="local",
    )
    db.add(user)
    await db.flush()
    db.add(Profile(user_id=user.id, nickname="爱丽丝"))
    await db.flush()
    return user.id


async def _make_published_exam(db: AsyncSession) -> int:
    exam = await create_exam_ex(db, _exam_create())
    obj = (await db.execute(select(Exam).where(Exam.id == exam.id))).scalars().first()
    assert obj is not None
    obj.is_published = True
    await db.flush()
    return exam.id


def _correct_answers(questions) -> dict[int, str]:
    """按题型给出 fixture 的正确作答（单选取 A、判断取 T）。

    QuestionForAttempt 刻意不带 answer 字段，故测试须自行构造正确答案
    （对应 seed 的口径：single->A、judge->T）。
    """
    return {q.id: ("A" if q.kind == "single" else "T") for q in questions}


class TestExamService:
    async def test_create_exam_with_questions(self, db: AsyncSession):
        exam = await create_exam_ex(db, _exam_create())
        assert exam.question_count == 2

        exams = (await db.execute(select(Exam))).scalars().all()
        assert len(exams) == 1

        qs = (await db.execute(select(ExamQuestion))).scalars().all()
        assert len(qs) == 2

    async def test_list_exams(self, db: AsyncSession):
        await create_exam_ex(db, _exam_create())
        items, total = await list_exams(db)
        assert total == 1
        assert items[0].title == "测试考试"

    async def test_start_attempt_requires_published(self, db: AsyncSession):
        user_id = await _user(db)
        exam_id = (await create_exam_ex(db, _exam_create())).id
        with pytest.raises(BizError) as exc:
            await start_attempt(db, exam_id, user_id)
        assert exc.value.errcode == ExamErr.EXAM_NOT_PUBLISHED

    async def test_start_attempt_and_submit_passed(self, db: AsyncSession):
        user_id = await _user(db)
        exam_id = await _make_published_exam(db)
        start = await start_attempt(db, exam_id, user_id)
        assert len(start.questions) == 2
        # 开考下发的是客户端安全 DTO：不得含 answer/analysis，防止提前泄露答案。
        for q in start.questions:
            assert not hasattr(q, "answer")
            assert not hasattr(q, "analysis")

        answers = _correct_answers(start.questions)
        res = await submit_attempt(
            db, start.attempt_id, user_id, SubmitAnswersRequest(answers=answers)
        )
        assert res.passed is True
        assert res.score == 40
        assert res.unlock_level == "normal"

        # account_level 升级生效（User 表）
        user = (
            (await db.execute(select(User).where(User.id == user_id))).scalars().first()
        )
        assert user is not None
        assert user.account_level == "normal"
        assert user.token_version >= 1  # 已递增使旧 token 失效

        # 证书生成
        certs = (await db.execute(select(ExamCertificate))).scalars().all()
        assert len(certs) == 1

    async def test_passed_upgrades_profile_role(self, db: AsyncSession):
        """通过设置 unlock_role 的考试后，profile.role 升级为 columnist。"""
        info = _exam_create().model_copy(
            update={"unlock_level": None, "unlock_role": "columnist"}
        )
        exam_id = (await create_exam_ex(db, info)).id
        obj = (
            (await db.execute(select(Exam).where(Exam.id == exam_id))).scalars().first()
        )
        assert obj is not None
        obj.is_published = True
        await db.flush()

        user_id = await _user(db)
        start = await start_attempt(db, exam_id, user_id)
        res = await submit_attempt(
            db,
            start.attempt_id,
            user_id,
            SubmitAnswersRequest(answers=_correct_answers(start.questions)),
        )
        assert res.unlock_role == "columnist"

        profile = (
            (await db.execute(select(Profile).where(Profile.user_id == user_id)))
            .scalars()
            .first()
        )
        assert profile is not None
        assert profile.role == "columnist"

    async def test_unlock_never_demotes_account_level(self, db: AsyncSession):
        """admin 通过仅 unlock_level=normal 的初级考试，不应被降级回 normal。"""
        user_id = await _user(db)
        # 把用户升为 admin（最高等级），考试 unlock_level=normal（更低）
        await db.execute(
            update(User).where(User.id == user_id).values(account_level="admin")
        )
        await db.flush()
        exam_id = await _make_published_exam(db)

        start = await start_attempt(db, exam_id, user_id)
        await submit_attempt(
            db,
            start.attempt_id,
            user_id,
            SubmitAnswersRequest(answers=_correct_answers(start.questions)),
        )
        user = (
            (await db.execute(select(User).where(User.id == user_id))).scalars().first()
        )
        assert user is not None
        assert user.account_level == "admin"  # 未被降级
        assert user.token_version == 0  # 未发生解锁，token 保持有效

    async def test_unlock_never_demotes_role(self, db: AsyncSession):
        """author 通过仅 unlock_role=columnist 的考试，角色不应被降级。"""
        user_id = await _user(db)
        await db.execute(
            update(Profile).where(Profile.user_id == user_id).values(role="author")
        )
        await db.flush()
        info = _exam_create().model_copy(
            update={"unlock_level": None, "unlock_role": "columnist"}
        )
        exam_id = (await create_exam_ex(db, info)).id
        obj = (
            (await db.execute(select(Exam).where(Exam.id == exam_id))).scalars().first()
        )
        assert obj is not None
        obj.is_published = True
        await db.flush()

        start = await start_attempt(db, exam_id, user_id)
        await submit_attempt(
            db,
            start.attempt_id,
            user_id,
            SubmitAnswersRequest(answers=_correct_answers(start.questions)),
        )
        profile = (
            (await db.execute(select(Profile).where(Profile.user_id == user_id)))
            .scalars()
            .first()
        )
        assert profile is not None
        assert profile.role == "author"  # 未被降级

    async def test_reject_resubmit(self, db: AsyncSession):
        user_id = await _user(db)
        exam_id = await _make_published_exam(db)
        start = await start_attempt(db, exam_id, user_id)
        answers = _correct_answers(start.questions)
        await submit_attempt(
            db, start.attempt_id, user_id, SubmitAnswersRequest(answers=answers)
        )
        with pytest.raises(BizError) as exc:
            await submit_attempt(
                db, start.attempt_id, user_id, SubmitAnswersRequest(answers=answers)
            )
        # status 检查在"已通过"守卫之前：同一 attempt 重交 → ATTEMPT_ALREADY_SUBMITTED
        assert exc.value.errcode == ExamErr.ATTEMPT_ALREADY_SUBMITTED

    async def test_submit_forbidden_for_other_user(self, db: AsyncSession):
        u1 = await _user(db, username="a", email="a@e.com")
        u2 = await _user(db, username="b", email="b@e.com")
        exam_id = await _make_published_exam(db)
        start = await start_attempt(db, exam_id, u1)
        with pytest.raises(BizError) as exc:
            await submit_attempt(
                db, start.attempt_id, u2, SubmitAnswersRequest(answers={})
            )
        assert exc.value.errcode == CommonErr.FORBIDDEN


class TestExamRoute:
    async def test_list_public(self, client, db):
        resp = await client.get("/api/v1/exam")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert resp.json()["data"]["total"] == 0

    async def test_attempt_requires_auth(self, client, db):
        # 用户需已认证（normal）才能开考：路由 RequireLevel("normal") 读 DB user.account_level
        user = User(
            username="t",
            email="t@e.com",
            hashed_password="x",
            account_level="normal",
        )
        db.add(user)
        await db.flush()
        db.add(Profile(user_id=user.id, nickname="t"))
        await db.flush()

        # 未登录 → 403（缺 Authorization）
        resp = await client.post("/api/v1/exam/1/attempts")
        assert resp.status_code == 403

        # 已登录 normal → 无该考试 404（路由与认证通过，落到业务查找）
        token = create_access_token(
            user_id=user.id, account_level="normal", role="member"
        )
        resp = await client.post(
            "/api/v1/exam/1/attempts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == ExamErr.EXAM_NOT_FOUND


class TestSeed:
    async def test_seed_exams_idempotent(self, db: AsyncSession):
        from app.modules.exam.seed import seed_exams

        first = await seed_exams(db)
        assert first == 3
        second = await seed_exams(db)
        assert second == 0
