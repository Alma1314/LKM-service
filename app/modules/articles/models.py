from __future__ import annotations

import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, now_iso


class ArticleCategory(Base):
    __tablename__: str = "article_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    articles: Mapped[list[Article]] = relationship(back_populates="category")


class Article(Base):
    __tablename__: str = "articles"
    # 文章列表热路径按 published 倒序，category_id 用于分组/聚合
    __table_args__: tuple[Index, ...] = (
        Index("ix_articles_published", "published"),
        Index("ix_articles_category_published", "category_id", "published"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("article_categories.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )  # draft|pending|published|rejected
    content: Mapped[str] = mapped_column(Text, nullable=False)
    publisher: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    published: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    likes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bookmarks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    category: Mapped[ArticleCategory | None] = relationship(back_populates="articles")
    tags: Mapped[list[Tag]] = relationship(
        secondary="article_tag", back_populates="articles", lazy="selectin"
    )
    comment_records: Mapped[list[ArticleComment]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",
        order_by="ArticleComment.created_at",
    )
    like_records: Mapped[list[ArticleLike]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )


class ArticleComment(Base):
    """文章评论。``parent_id`` 自引用支持一级回复（同 BlogComment 的写法）。"""

    __tablename__: str = "article_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("article_comments.id"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )

    article: Mapped[Article] = relationship(back_populates="comment_records")
    parent: Mapped[ArticleComment | None] = relationship(
        remote_side=[id], back_populates="replies"
    )
    replies: Mapped[list[ArticleComment]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )


class ArticleLike(Base):
    """文章点赞记录，复合主键保证同一用户对同一文章最多一条（点赞幂等）。"""

    __tablename__: str = "article_likes"

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    article: Mapped[Article] = relationship(back_populates="like_records")


class Tag(Base):
    """文章标签。多对多关联到文章。"""

    __tablename__: str = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    articles: Mapped[list[Article]] = relationship(
        secondary="article_tag", back_populates="tags"
    )


class ArticleTag(Base):
    """文章-标签复合主键关联表（同 ForumPostLike 的幂等写法）。"""

    __tablename__: str = "article_tag"

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id"), primary_key=True, index=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
