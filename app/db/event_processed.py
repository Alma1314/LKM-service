"""消费者幂等去重表（M1.3）。

全局 event_id（outbox_events.event_id → 透传到消费端 payload）作幂等键：消费者 handler
成功执行后把该 event_id 落此表；重放同一事件（relay 故障重投 / DLQ requeue 再投）消费端
按 event_id 查到已处理即 ack 跳过，避免二次副作用 —— 达成 at-least-once 下的去重收口。

未命中（首次）由 handler 自身保证单次副作用（points 另有 ref 幂等作次级守约）；本表是
队列层幂等框架的主键，跨 M2/M3 消费可靠事件均复用（对齐蓝图 §3.1「幂等键=event_id」）。
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, now_iso

logger = logging.getLogger(__name__)


class EventProcessed(Base):
    """消费端已处理的 outbox 事件幂等账本。event_id 即幂等键，直接用主键去重。"""

    __tablename__: str = "event_processed"

    # 幂等键 = outbox 全局 event_id（36 位 hex）。主键本身提供唯一约束：并发重复 INSERT
    # 由 DB 唯一性兜底（无唯一约束时靠先查后插，仍可能少数重复，主键到层最好）。
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # handler 首次成功执行的时间（审计/清理用）
    processed_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


async def already_processed(db: AsyncSession, event_id: str) -> bool:
    """该幂等键是否已有成功处理记录（命中 → 重放应跳过）。"""
    eid = await db.scalar(
        select(EventProcessed.event_id).where(EventProcessed.event_id == event_id)
    )
    return eid is not None


async def record_processed(db: AsyncSession, event_id: str) -> bool:
    """记录一笔成功处理；并发下撞主键（同 event 两个消费者）忽略、返回是否新增。"""
    db.add(EventProcessed(event_id=event_id))
    try:
        await db.commit()
        return True
    except IntegrityError:
        # 并发重复标记：另一进程已抢先落账，视为已记账不报错。
        await db.rollback()
        return False
