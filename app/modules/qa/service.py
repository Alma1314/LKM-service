"""QA 服务：发问（锁定悬赏 escrow）→ 回答 → 采纳派发 → 关闭退回。"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import (
    bump_collection_version,
    cached_read,
    collection_version,
    make_key,
)
from app.core.err import BizError
from app.db.models import QAAnswer, QAQuestion, QAQuestionImage
from app.db.repo import get_or_raise
from app.modules.common import PageData, paginate_offset, paginate_pages
from app.modules.points.service import reward, spend
from app.modules.qa.errors import QaErr
from app.modules.qa.schemas import (
    AnswerCreate,
    AnswerOut,
    QuestionCreate,
    QuestionDetail,
    QuestionOut,
)


async def create_question(
    db: AsyncSession, author_id: int, info: QuestionCreate
) -> QuestionOut:
    """发问：spend 锁定总悬赏 + 写 Question（同事务）。"""
    total = info.bounty_people * info.bounty_per_person
    # 先建 Question 拿 id（作为 spend 的 ref_id）
    q = QAQuestion(
        author_id=author_id,
        title=info.title,
        situation=info.situation,
        content=info.content,
        bounty_people=info.bounty_people,
        bounty_per_person=info.bounty_per_person,
        bounty_total=total,
        bounty_distributed=0,
        status="open",
    )
    db.add(q)
    await db.flush()
    if total > 0:
        # spend 锁定（余额不足抛 INSUFFICIENT_BALANCE，同事务回滚）
        await spend(db, author_id, total, "qa_escrow", "qa_question", str(q.id))
    if info.images:
        for i, url in enumerate(info.images):
            db.add(QAQuestionImage(question_id=q.id, url=url, sort=i))
    await db.flush()
    await bump_collection_version("qa")
    return _question_to_schema(q)


async def list_questions(
    db: AsyncSession, page: int = 1, limit: int = 20
) -> PageData[QuestionOut]:
    async def load() -> list[dict[str, Any]]:
        rows = (
            await db.execute(
                select(QAQuestion, func.count(QAAnswer.id))
                .outerjoin(QAAnswer, QAAnswer.question_id == QAQuestion.id)
                .group_by(QAQuestion.id)
                .order_by(QAQuestion.id.desc())
                .offset(paginate_offset(page, limit))
                .limit(limit)
            )
        ).all()
        return [
            QuestionOut.model_validate(q)
            .model_copy(update={"answer_count": ans_count})
            .model_dump()
            for q, ans_count in rows
        ]

    ver = await collection_version("qa")
    payload = await cached_read(make_key("qa:list", ver, page, limit), 60, load)
    # 分页元信息（total 单独查，不缓存）
    total = await db.scalar(select(func.count(QAQuestion.id))) or 0
    return PageData(
        items=[QuestionOut.model_validate(p) for p in payload],
        total=total,
        page=page,
        pages=paginate_pages(total, limit),
    )


async def get_question(db: AsyncSession, question_id: int) -> QuestionDetail:
    q = await get_or_raise(
        db, QAQuestion, QaErr.QUESTION_NOT_FOUND, QAQuestion.id == question_id
    )
    answers = (
        (
            await db.execute(
                select(QAAnswer)
                .where(QAAnswer.question_id == question_id)
                .order_by(QAAnswer.id.asc())
            )
        )
        .scalars()
        .all()
    )
    images = (
        (
            await db.execute(
                select(QAQuestionImage)
                .where(QAQuestionImage.question_id == question_id)
                .order_by(QAQuestionImage.sort.asc())
            )
        )
        .scalars()
        .all()
    )
    base = QuestionOut.model_validate(q).model_copy(
        update={"answer_count": len(answers)}
    )
    return QuestionDetail(
        **base.model_dump(),
        answers=[AnswerOut.model_validate(a) for a in answers],
        images=[img.url for img in images],
    )


async def create_answer(
    db: AsyncSession, question_id: int, author_id: int, info: AnswerCreate
) -> AnswerOut:
    q = await get_or_raise(
        db, QAQuestion, QaErr.QUESTION_NOT_FOUND, QAQuestion.id == question_id
    )
    if q.status != "open":
        raise BizError(QaErr.QUESTION_NOT_OPEN)
    a = QAAnswer(question_id=question_id, author_id=author_id, content=info.content)
    db.add(a)
    await db.flush()
    await bump_collection_version("qa")
    return AnswerOut.model_validate(a)


async def accept_answer(
    db: AsyncSession, question_id: int, answer_id: int, asker_id: int
) -> AnswerOut:
    """发问者采纳回答：防超发派发人均积分给回答者（同事务）。"""
    q = await get_or_raise(
        db, QAQuestion, QaErr.QUESTION_NOT_FOUND, QAQuestion.id == question_id
    )
    if q.author_id != asker_id:
        raise BizError(QaErr.NOT_ASKER)
    if q.status != "open":
        raise BizError(QaErr.QUESTION_NOT_OPEN)
    a = await get_or_raise(
        db,
        QAAnswer,
        QaErr.ANSWER_NOT_FOUND,
        QAAnswer.id == answer_id,
        QAAnswer.question_id == question_id,
    )
    if a.is_accepted:
        return AnswerOut.model_validate(a)
    # 防超发：已采纳数 >= 悬赏人数 → 拒
    accepted_count = (
        await db.scalar(
            select(func.count(QAAnswer.id)).where(
                QAAnswer.question_id == question_id,
                QAAnswer.is_accepted.is_(True),
            )
        )
        or 0
    )
    if accepted_count >= q.bounty_people:
        raise BizError(QaErr.BOUNTY_EXHAUSTED)
    if q.bounty_per_person > 0:
        await reward(
            db,
            a.author_id,
            q.bounty_per_person,
            "qa_accept",
            "qa_accept",
            f"{question_id}:{answer_id}",
        )
        q.bounty_distributed += q.bounty_per_person
    a.is_accepted = True
    q.accepted_answer_id = a.id
    await db.flush()
    await bump_collection_version("qa")
    return AnswerOut.model_validate(a)


async def close_question(
    db: AsyncSession,
    question_id: int,
    asker_id: int,
    accepted_answer_id: int | None = None,
) -> QuestionOut:
    """发问者关闭问题：可同时采纳一个回答；剩余 escrow 退回发问者。"""
    q = await get_or_raise(
        db, QAQuestion, QaErr.QUESTION_NOT_FOUND, QAQuestion.id == question_id
    )
    if q.author_id != asker_id:
        raise BizError(QaErr.NOT_ASKER)
    if q.status != "open":
        raise BizError(QaErr.QUESTION_NOT_OPEN)
    if accepted_answer_id is not None and accepted_answer_id != q.accepted_answer_id:
        await accept_answer(db, question_id, accepted_answer_id, asker_id)
        # 重新载入 q（accept 改了 distributed）
        q = await get_or_raise(
            db,
            QAQuestion,
            QaErr.QUESTION_NOT_FOUND,
            QAQuestion.id == question_id,
        )
    # 剩余 escrow 退回发问者
    refund = q.bounty_total - q.bounty_distributed
    if refund > 0:
        await reward(db, q.author_id, refund, "qa_refund", "qa_refund", str(q.id))
    q.status = "accepted" if q.accepted_answer_id is not None else "closed"
    await db.flush()
    await bump_collection_version("qa")
    return _question_to_schema(q)


def _question_to_schema(q: QAQuestion) -> QuestionOut:
    return QuestionOut.model_validate(q)
