from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeEngine

from app.modules.blog.models import BlogSeriesStatus
from app.modules.columns.models import (
    ColumnApplicationStatus,
    ColumnPostStatus,
    ColumnStatus,
)

if TYPE_CHECKING:
    from app.modules.auth.models import (
        TOTP,
        PasskeyCredential,
        RecoveryCode,
        RefreshToken,
        UserOAuth,
    )


class Base(DeclarativeBase):
    pass


def now_iso() -> datetime.datetime:
    """当前 UTC 时间（timezone-aware），用于默认值与比较。"""
    return datetime.datetime.now(datetime.UTC)


def expires_at(days: float = 0, minutes: float = 0) -> datetime.datetime:
    """从现在起 days/minutes 后的 UTC 时间（timezone-aware）。"""
    return datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        days=days, minutes=minutes
    )


class UTCDateTime(TypeDecorator[datetime.datetime]):
    """带时区的 UTC 时间列类型。底层使用 DateTime(timezone=True)"""

    impl: TypeEngine[Any] | type[TypeEngine[Any]] = DateTime(timezone=True)
    cache_ok: bool | None = True

    def process_result_value(
        self, value: datetime.datetime | None, dialect: Dialect
    ) -> datetime.datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=datetime.UTC)
        return value


class User(Base):
    __tablename__: str = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    account_level: Mapped[str] = mapped_column(
        String(10), nullable=False, default="local"
    )
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    locked_until: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )

    profile: Mapped[Profile] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    column_applications: Mapped[list[ColumnApplication]] = relationship(
        back_populates="user", foreign_keys="ColumnApplication.user_id"
    )
    owned_columns: Mapped[list[Column]] = relationship(back_populates="owner")
    posts: Mapped[list[ColumnPost]] = relationship(back_populates="author")
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(back_populates="user")
    oauth_bindings: Mapped[list[UserOAuth]] = relationship(back_populates="user")
    totp: Mapped[TOTP | None] = relationship(back_populates="user", uselist=False)
    recovery_codes: Mapped[list[RecoveryCode]] = relationship(back_populates="user")
    passkey_credentials: Mapped[list[PasskeyCredential]] = relationship(
        back_populates="user"
    )
    blog_series: Mapped[list[BlogSeries]] = relationship(back_populates="owner")
    forum_posts: Mapped[list[ForumPost]] = relationship(back_populates="author")
    forum_comments: Mapped[list[ForumComment]] = relationship(back_populates="user")
    uploaded_files: Mapped[list[LibraryFile]] = relationship(back_populates="uploader")
    exam_attempts: Mapped[list[ExamAttempt]] = relationship(back_populates="user")
    exam_certificates: Mapped[list[ExamCertificate]] = relationship(
        back_populates="user"
    )


class Profile(Base):
    __tablename__: str = "profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="profile")


class ColumnApplication(Base):
    __tablename__: str = "column_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[ColumnApplicationStatus] = mapped_column(
        String(20), nullable=False, default=ColumnApplicationStatus.PENDING
    )
    reviewer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    reviewed_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    user: Mapped[User] = relationship(
        foreign_keys=[user_id], back_populates="column_applications"
    )
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewer_id])
    column: Mapped[Column | None] = relationship(
        back_populates="application", uselist=False
    )


class Column(Base):
    __tablename__: str = "columns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("column_applications.id"), unique=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # —— 栏目展示字段（供前端社区「专栏」页富展示，见 docs 方案）——
    author_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    author_title: Mapped[str | None] = mapped_column(String(80), nullable=True)
    author_bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    follower_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subscribe_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    article_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    badges: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    board_id: Mapped[int | None] = mapped_column(ForeignKey("boards.id"), nullable=True)
    status: Mapped[ColumnStatus] = mapped_column(
        String(20), nullable=False, default=ColumnStatus.ACTIVE
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )

    owner: Mapped[User] = relationship(back_populates="owned_columns")
    application: Mapped[ColumnApplication | None] = relationship(
        back_populates="column"
    )
    posts: Mapped[list[ColumnPost]] = relationship(
        back_populates="column", cascade="all, delete-orphan"
    )


class ColumnPost(Base):
    __tablename__: str = "column_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    column_id: Mapped[int] = mapped_column(ForeignKey("columns.id"), nullable=False)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(300), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ColumnPostStatus] = mapped_column(
        String(20), nullable=False, default=ColumnPostStatus.PUBLISHED
    )
    cover_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )
    published_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )

    column: Mapped[Column] = relationship(back_populates="posts")
    author: Mapped[User] = relationship(back_populates="posts")


class ForumPost(Base):
    __tablename__: str = "forum_posts"
    # 列表热路径按 category 过滤 + (is_pinned, id) 排序 → 复合索引一次命中
    __table_args__: tuple[Index, ...] = (
        Index("ix_forum_posts_board_pinned_id", "board_id", "is_pinned", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    excerpt: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bookmark_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    forward_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )

    author: Mapped[User] = relationship(back_populates="forum_posts")
    board: Mapped[Board] = relationship(back_populates="posts")
    comments: Mapped[list[ForumComment]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )


class ForumComment(Base):
    __tablename__: str = "forum_comments"
    # 评论列表热路径按 post 过滤 + 按 floor 排序 → 复合索引
    __table_args__: tuple[Index, ...] = (
        Index("ix_forum_comments_post_floor", "post_id", "floor_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("forum_posts.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    floor_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("forum_comments.id"), nullable=True
    )
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    post: Mapped[ForumPost] = relationship(back_populates="comments")
    user: Mapped[User] = relationship(back_populates="forum_comments")
    parent: Mapped[ForumComment | None] = relationship(
        remote_side=[id], back_populates="replies"
    )
    replies: Mapped[list[ForumComment]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )


class ForumPostLike(Base):
    """论坛帖子点赞记录，复合主键保证同一用户对同一帖子最多一条（点赞幂等）。"""

    __tablename__: str = "forum_post_likes"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("forum_posts.id"), primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


class LibraryFile(Base):
    __tablename__: str = "library_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uploader_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # 内容寻址哈希（SHA3-256，16 进制 64 字符）
    sha3_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 引用计数：同一物理文件被多少条目引用，归零时清理磁盘文件。DB 持久化，替代内存 cache。
    ref_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 物理文件落盘路径（内容寻址：``files_store_dir/<hash[:2]>/<hash>``）。同一内容条目共享同一
    # ``storage_path``（不唯一），去重共享物理文件的关键；``stored_name`` 保持唯一作展示/定位。
    storage_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str] = mapped_column(
        String(100), nullable=False, default="application/octet-stream"
    )
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    category_id: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    uploader: Mapped[User] = relationship(back_populates="uploaded_files")


class BlogSeries(Base):
    __tablename__: str = "blog_series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    repo_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    status: Mapped[BlogSeriesStatus] = mapped_column(
        String(20), nullable=False, default=BlogSeriesStatus.ACTIVE
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )

    owner: Mapped[User] = relationship(back_populates="blog_series")
    comments: Mapped[list[BlogComment]] = relationship(
        back_populates="series", cascade="all, delete-orphan"
    )
    stars: Mapped[list[BlogStar]] = relationship(
        back_populates="series", cascade="all, delete-orphan"
    )


class BlogStar(Base):
    __tablename__: str = "blog_stars"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    series_id: Mapped[int] = mapped_column(
        ForeignKey("blog_series.id"), primary_key=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    user: Mapped[User] = relationship()
    series: Mapped[BlogSeries] = relationship(back_populates="stars")


class BlogComment(Base):
    __tablename__: str = "blog_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    series_id: Mapped[int] = mapped_column(ForeignKey("blog_series.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("blog_comments.id"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )

    user: Mapped[User] = relationship()
    series: Mapped[BlogSeries] = relationship(back_populates="comments")
    parent: Mapped[BlogComment | None] = relationship(
        remote_side=[id], back_populates="replies"
    )
    replies: Mapped[list[BlogComment]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )


class StarHopeQuestion(Base):
    __tablename__: str = "starhope_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    folder_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )


class StarHopeFolder(Base):
    __tablename__: str = "starhope_folders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )


class StarHopePracticeSession(Base):
    __tablename__: str = "starhope_practice_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    question_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    answers: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    results: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    time_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passing_grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )


class StarHopeAiAgent(Base):
    __tablename__: str = "starhope_ai_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    avatar: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    service: Mapped[str] = mapped_column(String(20), nullable=False, default="openai")
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    top_p: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=4096)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )


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


class UserBalance(Base):
    __tablename__: str = "user_balances"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )


class PointsLedger(Base):
    __tablename__: str = "points_ledger"
    # (user_id, ref_type, ref_id) 唯一：幂等——同一事件对同一用户不重复发分
    __table_args__: tuple[Any, ...] = (
        UniqueConstraint("user_id", "ref_type", "ref_id", name="uq_points_ledger_ref"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(50), nullable=False)
    ref_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


class QAQuestion(Base):
    __tablename__: str = "qa_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    situation: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    bounty_people: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    bounty_per_person: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bounty_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bounty_distributed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open"
    )  # open|accepted|closed
    accepted_answer_id: Mapped[int | None] = mapped_column(
        ForeignKey("qa_answers.id"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )


class QAAnswer(Base):
    __tablename__: str = "qa_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("qa_questions.id"), nullable=False
    )
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


class QAQuestionImage(Base):
    __tablename__: str = "qa_question_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("qa_questions.id"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


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
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
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
    user: Mapped[User] = relationship()
    parent: Mapped[ArticleComment | None] = relationship(
        remote_side=[id], back_populates="replies"
    )
    replies: Mapped[list[ArticleComment]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )


class ArticleLike(Base):
    """文章点赞记录，复合主键保证同一用户对同一文章最多一条（点赞幂等）。"""

    __tablename__: str = "article_likes"

    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    article: Mapped[Article] = relationship(back_populates="like_records")
    user: Mapped[User] = relationship()


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

    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


class Report(Base):
    """后台举报记录：用户对帖子/评论/文件等目标发起的举报，供后台审核。"""

    __tablename__: str = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # post/comment/file
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    reporter_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    handled_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    reporter: Mapped[User | None] = relationship(foreign_keys=[reporter_id])


class Board(Base):
    __tablename__: str = "boards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )  # active | inactive
    # 发言准入配置
    require_certified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    daily_post_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # 0=不限
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )

    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id])
    posts: Mapped[list[ForumPost]] = relationship(back_populates="board")


class BoardApplication(Base):
    __tablename__: str = "board_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending|approved|rejected
    reviewer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    reviewed_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )

    applicant: Mapped[User] = relationship(foreign_keys=[applicant_id])
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewer_id])


class BoardBan(Base):
    __tablename__: str = "board_bans"
    __table_args__ = (Index("ix_board_bans_board_user", "board_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    expires_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


class Exam(Base):
    __tablename__: str = "exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="exam"
    )  # exam | competition
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subject: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    pass_score: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    time_limit_min: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 认证考试：通过后自动升级的目标（竞赛为 None）。unlock_level 升 account_level，unlock_role 升 profile.role。
    unlock_level: Mapped[str | None] = mapped_column(String(10), nullable=True)
    unlock_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 竞赛时间窗（认证考试通常常开，starts_at/ends_at 为空即不限时窗）
    starts_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    ends_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )

    questions: Mapped[list[ExamQuestion]] = relationship(
        back_populates="exam", cascade="all, delete-orphan"
    )


class ExamQuestion(Base):
    __tablename__: str = "exam_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # single | judge
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON 字符串：[{"key":"A","text":"..."}] 单选多选项；judge 为空列表
    options: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    answer: Mapped[str] = mapped_column(
        String(200), nullable=False
    )  # single: "A"；judge: "T"/"F"
    analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    exam: Mapped[Exam] = relationship(back_populates="questions")


class ExamAttempt(Base):
    __tablename__: str = "exam_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="in_progress"
    )
    # JSON 字符串：{question_id: "用户答案"}（judge 存 "T"/"F"）
    answers: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    submitted_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    time_spent_s: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user: Mapped[User] = relationship(back_populates="exam_attempts")


class ExamCertificate(Base):
    __tablename__: str = "exam_certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cert_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    issued_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    exam: Mapped[Exam] = relationship()
    user: Mapped[User] = relationship(back_populates="exam_certificates")
