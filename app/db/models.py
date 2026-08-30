from __future__ import annotations

import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
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
from app.modules.content.column_models import (
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
    content_items: Mapped[list[ContentItem]] = relationship(
        back_populates="author", foreign_keys="ContentItem.author_id"
    )
    content_comments: Mapped[list[ContentComment]] = relationship(back_populates="user")
    uploaded_files: Mapped[list[LibraryFile]] = relationship(back_populates="uploader")
    exam_attempts: Mapped[list[ExamAttempt]] = relationship(back_populates="user")
    exam_certificates: Mapped[list[ExamCertificate]] = relationship(
        back_populates="user"
    )
    following: Mapped[list[UserFollow]] = relationship(
        back_populates="follower",
        foreign_keys="UserFollow.follower_id",
        cascade="all, delete-orphan",
    )
    followers: Mapped[list[UserFollow]] = relationship(
        back_populates="following",
        foreign_keys="UserFollow.following_id",
        cascade="all, delete-orphan",
    )
    board_follows: Mapped[list[BoardFollow]] = relationship(
        back_populates="follower",
        foreign_keys="BoardFollow.follower_id",
        cascade="all, delete-orphan",
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


class ContentType(StrEnum):
    """统一内容模型的内容体裁判别列。

    五套旧内容表（forum_posts / articles / column_posts / blog 发布产物）收敛为
    一张 content_items 表，用本枚举区分展示语义：
    - discussion：普通讨论帖（原 forum_posts，无审稿，发即 published）
    - article：官方发布文章（原 articles，含官方字段 publisher/department，含 news 分类）
    - column_post：专栏连载（原 column_posts，挂 column_id，追更）
    - blog_post：博客发布产物（原 blog_series 发布后落成的展示内容）
    """

    DISCUSSION = "discussion"
    ARTICLE = "article"
    COLUMN_POST = "column_post"
    BLOG_POST = "blog_post"
    QA = "qa"


class ContentStatus(StrEnum):
    """content_items.status 状态机。

    各体裁对齐旧语义：
    - discussion 恒 PUBLISHED（发即公开）
    - article / column_post / blog_post 支持 draft / pending / published / rejected
    """

    DRAFT = "draft"
    PENDING = "pending"
    PUBLISHED = "published"
    REJECTED = "rejected"


class ContentItem(Base):
    """统一内容表：五套旧内容表（forum_posts/articles/column_posts/blog 发布产物）收敛。

    用 ``content_type`` 判别（discussion/article/column_post/blog_post），``board_id``
    作唯一分类轴，``author_id``（user FK）与 ``publisher``/``department``（官方字符串）
    二选一表达作者身份。``column_id`` 指向连载容器（仅 column_post 用）。
    """

    __tablename__: str = "content_items"
    __table_args__: tuple[Any, ...] = (
        Index(
            "ix_content_board_type_status", "board_id", "content_type", "status", "id"
        ),
        Index("ix_content_board_pinned", "board_id", "is_pinned", "id"),
        Index("ix_content_status_pinned", "status", "is_pinned", "id"),
        # 时间线按体裁扫描：content_type+status 过滤，created_at,id 排序，命中索引免 filesort
        Index(
            "ix_content_type_status_created",
            "content_type",
            "status",
            "created_at",
            "id",
        ),
        Index("ix_content_published", "published_at"),
        Index("ix_content_slug", "slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # 统一分类轴
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id"), nullable=False)
    # 作者：user FK 与官方字符串二选一
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    publisher: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 专栏连载容器（仅 column_post）
    column_id: Mapped[int | None] = mapped_column(
        ForeignKey("columns.id"), nullable=True, index=True
    )
    slug: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # QA 提问关联（仅 content_type == 'qa'）：指向 qa_questions，论坛条目可跳转提问详情
    qa_question_id: Mapped[int | None] = mapped_column(
        ForeignKey("qa_questions.id"), nullable=True, index=True
    )
    # 内容本体
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    excerpt: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cover: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    lang: Mapped[str | None] = mapped_column(String(8), nullable=True)
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # 状态：discussion 恒 published；其余支持 draft/pending/published/rejected
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="published")
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 互动计数（论坛完整模式）
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
    published_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )

    author: Mapped[User | None] = relationship(
        back_populates="content_items", foreign_keys=[author_id]
    )
    board: Mapped[Board] = relationship()
    column: Mapped[Column | None] = relationship()
    qa_question: Mapped[QAQuestion | None] = relationship(foreign_keys=[qa_question_id])
    comments: Mapped[list[ContentComment]] = relationship(
        back_populates="content_item", cascade="all, delete-orphan"
    )
    like_records: Mapped[list[ContentLike]] = relationship(
        back_populates="content", cascade="all, delete-orphan"
    )


class ContentComment(Base):
    """统一内容评论（对齐原 forum_comments 的完整模式：floor_number/parent_id/like_count）。"""

    __tablename__: str = "content_comments"
    __table_args__: tuple[Any, ...] = (
        Index("ix_content_comments_item_floor", "content_id", "floor_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_id: Mapped[int] = mapped_column(
        ForeignKey("content_items.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    floor_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("content_comments.id"), nullable=True
    )
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    content_item: Mapped[ContentItem] = relationship(back_populates="comments")
    user: Mapped[User] = relationship(back_populates="content_comments")
    parent: Mapped[ContentComment | None] = relationship(
        remote_side=[id], back_populates="replies"
    )
    replies: Mapped[list[ContentComment]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )


class ContentLike(Base):
    """统一内容点赞记录，复合主键保证同一用户对同一内容最多一条（点赞幂等）。"""

    __tablename__: str = "content_likes"

    content_id: Mapped[int] = mapped_column(
        ForeignKey("content_items.id"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    content: Mapped[ContentItem] = relationship(back_populates="like_records")
    user: Mapped[User] = relationship()


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
    contents: Mapped[list[BlogContent]] = relationship(
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


class BlogContent(Base):
    """系列仓库内单个文件的正文（DB 为主存储）。

    每 series 下每个 path 一行（UniqueConstraint(series_id, path)），保存当前内容。
    git 裸仓库降级为版本快照层，文本内容的事实源在此表。``sha3`` 记录内容指纹，
    供将来 git 快照经 ``git http-backend`` push 时做变更检测/懒回填。
    """

    __tablename__: str = "blog_content"
    __table_args__: tuple[Any, ...] = (
        UniqueConstraint("series_id", "path", name="uq_blog_content_series_path"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series_id: Mapped[int] = mapped_column(
        ForeignKey("blog_series.id"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sha3: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )

    series: Mapped[BlogSeries] = relationship()


class BlogRepoQuarantine(Base):
    """被周对账隔离的孤儿 git 仓库台账（隔离=仅入库不移动目录）。

    repo_name 对应 ``<repo_name>.git``；src_dir 记录隔离前绝对路径便于恢复。
    对账按 quarantined_at 年龄超阈值才物理删除目录。delete_series 正常删仓库时同步清行。
    """

    __tablename__: str = "blog_repo_quarantine"
    __table_args__: tuple[Any, ...] = (
        UniqueConstraint("repo_name", name="uq_blog_repo_quarantine_repo_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_name: Mapped[str] = mapped_column(String(120), nullable=False)
    src_dir: Mapped[str] = mapped_column(String(500), nullable=False)
    quarantined_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
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
        # 排行榜日/周窗口聚合：`created_at >= since AND delta > 0`，命中索引免全表扫
        Index("ix_ledger_created_delta", "created_at", "delta"),
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


class UserBehaviorStat(Base):
    __tablename__: str = "user_behavior_stats"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    stats: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_checkin_date: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )  # YYYY-MM-DD
    checkin_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )


class Achievement(Base):
    __tablename__: str = "achievements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)  # a1..a12
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="special")
    icon: Mapped[str] = mapped_column(String(80), nullable=False, default="tabler:star")
    name_key: Mapped[str] = mapped_column(String(120), nullable=False)
    desc_key: Mapped[str] = mapped_column(String(160), nullable=False)
    type: Mapped[str] = mapped_column(
        String(40), nullable=False
    )  # onboarding/post_count/featured_count/accepted_answers/approved_files/checkin_streak/project_count/column_articles
    threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reward_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class UserAchievement(Base):
    __tablename__: str = "user_achievements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    achievement_id: Mapped[int] = mapped_column(
        ForeignKey("achievements.id"), nullable=False
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unlocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    unlocked_at: Mapped[datetime.datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    __table_args__ = (
        UniqueConstraint("user_id", "achievement_id", name="uq_user_achievement"),
    )


class Task(Base):
    __tablename__: str = "task_definitions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)  # t1..t5
    title_key: Mapped[str] = mapped_column(String(120), nullable=False)
    desc_key: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(
        String(40), nullable=False
    )  # checkin/post/answer/like/file_upload
    requirement_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reward_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class UserTaskProgress(Base):
    __tablename__: str = "user_task_progress"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("task_definitions.id"), nullable=False
    )
    period_date: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # YYYY-MM-DD，每日任务按天
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rewarded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    __table_args__ = (
        UniqueConstraint(
            "user_id", "task_id", "period_date", name="uq_user_task_period"
        ),
    )


class ExchangeItem(Base):
    __tablename__: str = "exchange_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)  # e1..e6
    name_key: Mapped[str] = mapped_column(String(120), nullable=False)
    desc_key: Mapped[str] = mapped_column(String(200), nullable=False)
    points_cost: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stock: Mapped[int] = mapped_column(
        Integer, nullable=False, default=-1
    )  # -1 无限/虚拟
    is_virtual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class QAQuestion(Base):
    __tablename__: str = "qa_questions"
    # 问答列表按 category + id 倒序，status 用于状态筛选；无索引则列表页全表扫
    __table_args__: tuple[Index, ...] = (
        Index("ix_qa_question_category_id", "category", "id"),
        Index("ix_qa_question_status_id", "status", "id"),
    )

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
    category: Mapped[str] = mapped_column(
        String(20), nullable=False, default="help"
    )  # help|volunteer（前端 tab 分类）
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
    # 按 question_id 拉回答 / 判定是否已采纳；无索引时按提问拉回答全表扫
    __table_args__: tuple[Index, ...] = (
        Index("ix_qa_answer_question", "question_id"),
        Index("ix_qa_answer_question_accepted", "question_id", "is_accepted"),
    )

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
    __table_args__: tuple[Index, ...] = (
        Index("ix_qa_question_image_question", "question_id"),
    )

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
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
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
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id"), primary_key=True, index=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


class Report(Base):
    """后台举报记录：用户对帖子/评论/文件等目标发起的举报，供后台审核。"""

    __tablename__: str = "reports"
    __table_args__: tuple[Any, ...] = (
        # 后台「按 status 分页列的待办举报」高频查询：条件 status + 排序 id desc
        Index("ix_reports_status_id", "status", "id"),
        Index("ix_reports_target", "type", "target_id"),
    )

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
    # 子板块挂父板块（板块广场嵌套展示：父=大分类，子=细分板块）
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("boards.id"), nullable=True, index=True
    )
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
    parent: Mapped[Board | None] = relationship(
        remote_side=[id], back_populates="children"
    )
    children: Mapped[list[Board]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    followers: Mapped[list[BoardFollow]] = relationship(
        back_populates="board",
        foreign_keys="BoardFollow.board_id",
        cascade="all, delete-orphan",
    )


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
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id"), nullable=False, index=True
    )
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
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
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
    exam_id: Mapped[int] = mapped_column(
        ForeignKey("exams.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cert_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    issued_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )

    exam: Mapped[Exam] = relationship()
    user: Mapped[User] = relationship(back_populates="exam_certificates")


class Project(Base):
    __tablename__: str = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    is_incubated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # ———————— 项目广场展示字段（后端扩充，供 GET /projects 展示） ————————
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="showcase"
    )  # recruiting(招募中) | showcase(展示)
    is_recruiting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    background: Mapped[str | None] = mapped_column(Text, nullable=True)
    goals: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    team_intro: Mapped[str | None] = mapped_column(Text, nullable=True)
    recruiting_roles: Mapped[list] = mapped_column(JSON, default=list)  # [str] 招募角色
    tags: Mapped[list] = mapped_column(JSON, default=list)  # [str]
    reports: Mapped[list] = mapped_column(
        JSON, default=list
    )  # [{title,content,revision,date}] 进展报告
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )  # active | archived
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )

    applicant: Mapped[User] = relationship(foreign_keys=[applicant_id])
    members: Mapped[list[ProjectMember]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectApplication(Base):
    __tablename__: str = "project_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    # 贡献成员清单：JSON 文本（[{display_name, role_in_project, user_id?}]），跨驱动用 Text
    member_claims: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
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


class ProjectMember(Base):
    __tablename__: str = "project_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )  # 空 = 非注册成员，仅 display_name
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role_in_project: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User | None] = relationship(foreign_keys=[user_id])


class RolePermission(Base):
    """RBAC：复合角色→权限点 映射。角色即 ``{account_level}:{profile.role}``。"""

    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_name", "permission"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_name: Mapped[str] = mapped_column(String(40), nullable=False)
    permission: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )


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


class ModerationRule(Base):
    """自动审校规则（关键词/域名黑名单，正则可选）：读时降权 / 隐藏。

    * ``action="derank"``：命中后按 ``weight`` 压低 sort_score，不剔除。
    * ``action="hide"``：命中后直接在时间线合流前剔除。
    不改内容状态、无 pending/hidden 拦截状态机——纯读时评估。
    """

    __tablename__: str = "moderation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 关键词 / 域名 / 正则（is_regex=True）
    pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    is_regex: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # derank | hide
    action: Mapped[str] = mapped_column(String(10), nullable=False, default="derank")
    # 降权力度 0..1（derank 用；hide 忽略直接过滤）
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    # 命中范围：content=标题+正文；预留（后续可加 author/board 级）
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="content")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, nullable=False, default=now_iso, onupdate=now_iso
    )
