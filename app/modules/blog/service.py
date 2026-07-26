import datetime

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.err import BizError, ErrCode
from app.db.models import BlogComment, BlogSeries, BlogStar, Profile
from app.modules.blog import git_svc
from app.modules.auth.schemas import ProfileInfo
from app.modules.blog.schemas import (
    BlogCommentCreate,
    BlogCommentInfo,
    BlogSeriesCreate,
    BlogSeriesDetail,
    BlogSeriesInfo,
    BlogSeriesUpdate,
    BlogStarStatus,
)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ---- private converters ----


def _series_to_info(
    s: BlogSeries, star_count: int = 0, is_starred: bool = False
) -> BlogSeriesInfo:
    return BlogSeriesInfo(
        id=s.id,
        owner_id=s.owner_id,
        title=s.title,
        description=s.description,
        cover_url=s.cover_url,
        repo_name=s.repo_name,
        status=s.status,
        created_at=s.created_at,
        updated_at=s.updated_at,
        star_count=star_count,
        is_starred=is_starred,
    )


def _comment_to_info(c: BlogComment, profile: ProfileInfo | None = None) -> BlogCommentInfo:
    return BlogCommentInfo(
        id=c.id,
        user_id=c.user_id,
        series_id=c.series_id,
        content=c.content,
        parent_id=c.parent_id,
        created_at=c.created_at,
        updated_at=c.updated_at,
        profile=profile,
        replies=[],
    )


# ---- star helpers ----


def _star_count(db: Session, series_id: int) -> int:
    return (
        db.query(func.count(BlogStar.user_id))
        .filter(BlogStar.series_id == series_id)
        .scalar()
        or 0
    )


def _is_starred(db: Session, series_id: int, user_id: int) -> bool:
    return (
        db.query(BlogStar)
        .filter(BlogStar.series_id == series_id, BlogStar.user_id == user_id)
        .first()
        is not None
    )


def _get_profile(db: Session, user_id: int) -> ProfileInfo | None:
    profile = db.query(Profile).filter(Profile.user_id == user_id).first()
    if profile:
        return ProfileInfo(nickname=profile.nickname, avatar=profile.avatar, role=profile.role)
    return None


# ---- series CRUD ----


def create_series(db: Session, user_id: int, info: BlogSeriesCreate) -> BlogSeriesInfo:
    existing = (
        db.query(BlogSeries).filter(BlogSeries.repo_name == info.repo_name).first()
    )
    if existing:
        raise BizError(ErrCode.INVALID_INPUT, "Repository name already taken")

    git_svc.init_bare_repo(info.repo_name)

    series = BlogSeries(
        owner_id=user_id,
        title=info.title,
        description=info.description,
        cover_url=info.cover_url,
        repo_name=info.repo_name,
    )
    db.add(series)
    db.flush()
    db.refresh(series)
    return _series_to_info(series)


def list_series(
    db: Session, current_user_id: int | None = None
) -> list[BlogSeriesInfo]:
    items = db.query(BlogSeries).order_by(BlogSeries.id.desc()).all()
    result = []
    for s in items:
        sc = _star_count(db, s.id)
        starred = _is_starred(db, s.id, current_user_id) if current_user_id else False
        result.append(_series_to_info(s, star_count=sc, is_starred=starred))
    return result


def get_series(
    db: Session, series_id: int, current_user_id: int | None = None
) -> BlogSeriesDetail:
    series = db.query(BlogSeries).filter(BlogSeries.id == series_id).first()
    if not series:
        raise BizError(ErrCode.BLOG_SERIES_NOT_FOUND)

    sc = _star_count(db, series_id)
    starred = (
        _is_starred(db, series_id, current_user_id) if current_user_id else False
    )

    file_tree = None
    if git_svc.ensure_repo_has_commits(series.repo_name):
        file_tree = git_svc.get_file_tree(series.repo_name)

    return BlogSeriesDetail(
        id=series.id,
        owner_id=series.owner_id,
        title=series.title,
        description=series.description,
        cover_url=series.cover_url,
        repo_name=series.repo_name,
        status=series.status,
        created_at=series.created_at,
        updated_at=series.updated_at,
        star_count=sc,
        is_starred=starred,
        file_tree=file_tree,
    )


def update_series(
    db: Session, series_id: int, user_id: int, info: BlogSeriesUpdate
) -> BlogSeriesInfo:
    series = db.query(BlogSeries).filter(BlogSeries.id == series_id).first()
    if not series:
        raise BizError(ErrCode.BLOG_SERIES_NOT_FOUND)
    if series.owner_id != user_id:
        raise BizError(ErrCode.FORBIDDEN)

    if info.title is not None:
        series.title = info.title
    if info.description is not None:
        series.description = info.description
    if info.cover_url is not None:
        series.cover_url = info.cover_url
    if info.status is not None:
        series.status = info.status
    series.updated_at = _now()

    db.flush()
    db.refresh(series)
    return _series_to_info(series)


def delete_series(db: Session, series_id: int, user_id: int) -> None:
    series = db.query(BlogSeries).filter(BlogSeries.id == series_id).first()
    if not series:
        raise BizError(ErrCode.BLOG_SERIES_NOT_FOUND)
    if series.owner_id != user_id:
        raise BizError(ErrCode.FORBIDDEN)

    git_svc.delete_repo(series.repo_name)
    db.delete(series)
    db.flush()


# ---- star toggle ----


def toggle_star(db: Session, series_id: int, user_id: int) -> BlogStarStatus:
    series = db.query(BlogSeries).filter(BlogSeries.id == series_id).first()
    if not series:
        raise BizError(ErrCode.BLOG_SERIES_NOT_FOUND)

    existing = (
        db.query(BlogStar)
        .filter(BlogStar.series_id == series_id, BlogStar.user_id == user_id)
        .first()
    )

    if existing:
        db.delete(existing)
        db.flush()
        return BlogStarStatus(starred=False, star_count=_star_count(db, series_id))

    star = BlogStar(user_id=user_id, series_id=series_id)
    db.add(star)
    db.flush()
    return BlogStarStatus(starred=True, star_count=_star_count(db, series_id))


# ---- comments ----


def create_comment(
    db: Session, series_id: int, user_id: int, info: BlogCommentCreate
) -> BlogCommentInfo:
    series = db.query(BlogSeries).filter(BlogSeries.id == series_id).first()
    if not series:
        raise BizError(ErrCode.BLOG_SERIES_NOT_FOUND)

    if info.parent_id is not None:
        parent = (
            db.query(BlogComment).filter(BlogComment.id == info.parent_id).first()
        )
        if not parent or parent.series_id != series_id:
            raise BizError(ErrCode.INVALID_INPUT, "Parent comment not found")

    comment = BlogComment(
        user_id=user_id,
        series_id=series_id,
        content=info.content,
        parent_id=info.parent_id,
    )
    db.add(comment)
    db.flush()
    db.refresh(comment)
    return _comment_to_info(comment, profile=_get_profile(db, user_id))


def list_comments(db: Session, series_id: int) -> list[BlogCommentInfo]:
    series = db.query(BlogSeries).filter(BlogSeries.id == series_id).first()
    if not series:
        raise BizError(ErrCode.BLOG_SERIES_NOT_FOUND)

    comments = (
        db.query(BlogComment)
        .filter(BlogComment.series_id == series_id)
        .order_by(BlogComment.created_at.asc())
        .all()
    )

    user_ids = {c.user_id for c in comments}
    profiles: dict[int, ProfileInfo | None] = {}
    for uid in user_ids:
        profiles[uid] = _get_profile(db, uid)

    comment_map: dict[int, BlogCommentInfo] = {}
    roots: list[BlogCommentInfo] = []

    for c in comments:
        info = _comment_to_info(c, profile=profiles.get(c.user_id))
        comment_map[c.id] = info

    for c in comments:
        info = comment_map[c.id]
        if c.parent_id is not None and c.parent_id in comment_map:
            comment_map[c.parent_id].replies.append(info)
        else:
            roots.append(info)

    return roots


def delete_comment(db: Session, series_id: int, comment_id: int, user_id: int) -> None:
    comment = (
        db.query(BlogComment)
        .filter(BlogComment.id == comment_id, BlogComment.series_id == series_id)
        .first()
    )
    if not comment:
        raise BizError(ErrCode.BLOG_COMMENT_NOT_FOUND)
    if comment.user_id != user_id:
        raise BizError(ErrCode.FORBIDDEN)
    db.delete(comment)
    db.flush()


# ---- files ----


def get_file_content(db: Session, series_id: int, filepath: str) -> dict:
    series = db.query(BlogSeries).filter(BlogSeries.id == series_id).first()
    if not series:
        raise BizError(ErrCode.BLOG_SERIES_NOT_FOUND)
    content = git_svc.read_file(series.repo_name, filepath)
    return {"filepath": filepath, "content": content}
