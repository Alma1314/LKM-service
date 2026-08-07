import datetime
import json
import re

from sqlalchemy.orm import Session

from app.core.err import BizError, ErrCode
from app.db.models import ForumComment, ForumPost, User
from app.modules.forum.models import FORUM_TABLE_PLAN
from app.modules.forum.schemas import CommentCreate, CommentInfo, PageData, PostCreate, PostInfo


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _author_name(user: User) -> str:
    if user.profile and user.profile.nickname:
        return user.profile.nickname
    return user.username


def _excerpt_of(content: str, limit: int = 150) -> str:
    text = re.sub(r"<[^>]+>", " ", content)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _load_tags(raw: str) -> list[str]:
    try:
        tags = json.loads(raw)
        return tags if isinstance(tags, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _post_to_schema(p: ForumPost, author_name: str) -> PostInfo:
    return PostInfo(
        id=p.id,
        title=p.title,
        excerpt=p.excerpt,
        content=p.content,
        author_id=p.author_id,
        author_name=author_name,
        category_id=p.category_id,
        tags=_load_tags(p.tags),
        is_pinned=p.is_pinned,
        is_featured=p.is_featured,
        view_count=p.view_count,
        like_count=p.like_count,
        comment_count=p.comment_count,
        bookmark_count=p.bookmark_count,
        created_at=p.created_at,
    )


def _comment_to_schema(c: ForumComment, author_name: str) -> CommentInfo:
    return CommentInfo(
        id=c.id,
        post_id=c.post_id,
        author_id=c.user_id,
        author_name=author_name,
        content=c.content,
        floor_number=c.floor_number,
        parent_id=c.parent_id,
        like_count=c.like_count,
        created_at=c.created_at,
    )


def _author_map(db: Session, user_ids: list[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    users = db.query(User).filter(User.id.in_(set(user_ids))).all()
    return {u.id: _author_name(u) for u in users}


def get_forum_plan() -> dict:
    return {
        "status": "implemented_minimal",
        "tables": FORUM_TABLE_PLAN,
        "next_steps": [
            "Add comment delete API",
            "Add post moderation and report workflow",
            "Add category table and board relation",
        ],
    }


def list_posts(
    db: Session,
    page: int = 1,
    limit: int = 20,
    category_id: str | None = None,
) -> PageData[PostInfo]:
    query = db.query(ForumPost)
    if category_id:
        query = query.filter(ForumPost.category_id == category_id)

    total = query.count()
    posts = (
        query.order_by(ForumPost.is_pinned.desc(), ForumPost.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    names = _author_map(db, [p.author_id for p in posts])
    items = [_post_to_schema(p, names.get(p.author_id, "")) for p in posts]
    return PageData(items=items, total=total, page=page, pages=(total + limit - 1) // limit)


def get_post(db: Session, post_id: int, bump_view: bool = False) -> PostInfo:
    post = db.query(ForumPost).filter(ForumPost.id == post_id).first()
    if not post:
        raise BizError(ErrCode.FORUM_POST_NOT_FOUND)

    if bump_view:
        post.view_count += 1
        db.flush()

    names = _author_map(db, [post.author_id])
    return _post_to_schema(post, names.get(post.author_id, ""))


def create_post(db: Session, author_id: int, info: PostCreate) -> PostInfo:
    post = ForumPost(
        author_id=author_id,
        category_id=info.category_id,
        title=info.title,
        excerpt=_excerpt_of(info.content),
        content=info.content,
        tags=json.dumps(info.tags, ensure_ascii=False),
    )
    db.add(post)
    db.flush()
    db.refresh(post)

    names = _author_map(db, [post.author_id])
    return _post_to_schema(post, names.get(post.author_id, ""))


def delete_post(db: Session, post_id: int, current_user_id: int) -> None:
    post = db.query(ForumPost).filter(ForumPost.id == post_id).first()
    if not post:
        raise BizError(ErrCode.FORUM_POST_NOT_FOUND)
    if post.author_id != current_user_id:
        raise BizError(ErrCode.FORBIDDEN)
    db.delete(post)
    db.flush()


def like_post(db: Session, post_id: int) -> int:
    post = db.query(ForumPost).filter(ForumPost.id == post_id).first()
    if not post:
        raise BizError(ErrCode.FORUM_POST_NOT_FOUND)
    post.like_count += 1
    db.flush()
    return post.like_count


def list_comments(
    db: Session,
    post_id: int,
    page: int = 1,
    limit: int = 20,
) -> PageData[CommentInfo]:
    post = db.query(ForumPost).filter(ForumPost.id == post_id).first()
    if not post:
        raise BizError(ErrCode.FORUM_POST_NOT_FOUND)

    query = db.query(ForumComment).filter(ForumComment.post_id == post_id)
    total = query.count()
    comments = (
        query.order_by(ForumComment.floor_number.asc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    names = _author_map(db, [c.user_id for c in comments])
    items = [_comment_to_schema(c, names.get(c.user_id, "")) for c in comments]
    return PageData(items=items, total=total, page=page, pages=(total + limit - 1) // limit)


def create_comment(
    db: Session,
    post_id: int,
    user_id: int,
    info: CommentCreate,
) -> CommentInfo:
    post = db.query(ForumPost).filter(ForumPost.id == post_id).first()
    if not post:
        raise BizError(ErrCode.FORUM_POST_NOT_FOUND)

    if info.parent_id is not None:
        parent = (
            db.query(ForumComment)
            .filter(
                ForumComment.id == info.parent_id,
                ForumComment.post_id == post_id,
            )
            .first()
        )
        if not parent:
            raise BizError(ErrCode.FORUM_COMMENT_NOT_FOUND)

    floor = (
        db.query(ForumComment)
        .filter(ForumComment.post_id == post_id)
        .order_by(ForumComment.floor_number.desc())
        .first()
    )
    next_floor = floor.floor_number + 1 if floor else 1

    comment = ForumComment(
        post_id=post_id,
        user_id=user_id,
        content=info.content,
        floor_number=next_floor,
        parent_id=info.parent_id,
    )
    db.add(comment)
    post.comment_count += 1
    db.flush()
    db.refresh(comment)

    names = _author_map(db, [comment.user_id])
    return _comment_to_schema(comment, names.get(comment.user_id, ""))
