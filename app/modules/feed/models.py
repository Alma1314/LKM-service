from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, now_iso  # 注意 db.base 而非 db.models

if TYPE_CHECKING:
    from app.modules.auth.models import User
    from app.modules.content.models import Board


class UserFollow(Base):
    """用户关注关系（软删墓碑）：follower 关注 following。

    唯一约束针对``(follower_id, following_id)``——软删行保留以便幂等重关注；
    活动关注统一 ``deleted_at IS NULL``。反向查「谁关注了我」走 following_id 索引。
    """

    __tablename__: str = "user_follows"
    __table_args__: tuple[UniqueConstraint, Index, Index] = (
        UniqueConstraint("follower_id", "following_id", name="uq_user_follows_pair"),
        Index("ix_user_follows_following_created", "following_id", "created_at"),
        # "我关注了谁"（follower 视角）按时间排序/分页
        Index("ix_user_follows_follower_created", "follower_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    follower_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    following_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    follower: Mapped[User] = relationship(
        back_populates="following", foreign_keys=[follower_id]
    )
    following: Mapped[User] = relationship(
        back_populates="followers", foreign_keys=[following_id]
    )


class BoardFollow(Base):
    """用户关注版块关系（软删墓碑）：follower 关注 board_id。"""

    __tablename__: str = "board_follows"
    __table_args__: tuple[UniqueConstraint, Index] = (
        UniqueConstraint("follower_id", "board_id", name="uq_board_follows_pair"),
        Index("ix_board_follows_board", "board_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    follower_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id"), nullable=False)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    follower: Mapped[User] = relationship(
        back_populates="board_follows", foreign_keys=[follower_id]
    )
    board: Mapped[Board] = relationship(back_populates="followers")
