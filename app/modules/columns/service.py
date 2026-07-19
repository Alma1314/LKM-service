import datetime

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.core.err import BizError, ErrCode
from app.db.models import Column, ColumnApplication, ColumnPost
from app.modules.columns.models import COLUMN_TABLE_PLAN, ColumnApplicationStatus, ColumnPostStatus
from app.modules.columns.schemas import (
    ColumnApplicationCreate,
    ColumnApplicationInfo,
    ColumnApplicationReview,
    ColumnInfo,
    ColumnPostCreate,
    ColumnPostInfo,
)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _app_to_schema(a: ColumnApplication) -> ColumnApplicationInfo:
    return ColumnApplicationInfo(
        id=a.id,
        user_id=a.user_id,
        title=a.title,
        description=a.description,
        reason=a.reason,
        status=a.status,
        reviewer_id=a.reviewer_id,
        review_note=a.review_note,
        created_at=a.created_at,
        reviewed_at=a.reviewed_at,
    )


def _col_to_schema(c: Column) -> ColumnInfo:
    return ColumnInfo(
        id=c.id,
        owner_id=c.owner_id,
        application_id=c.application_id,
        title=c.title,
        description=c.description,
        cover_url=c.cover_url,
        status=c.status,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _post_to_schema(p: ColumnPost) -> ColumnPostInfo:
    return ColumnPostInfo(
        id=p.id,
        column_id=p.column_id,
        author_id=p.author_id,
        title=p.title,
        summary=p.summary,
        status=p.status,
        created_at=p.created_at,
        updated_at=p.updated_at,
        published_at=p.published_at,
    )


def get_column_plan() -> dict:
    return {
        "status": "implemented_minimal",
        "tables": COLUMN_TABLE_PLAN,
        "next_steps": [
            "Add authentication before write operations",
            "Restrict review APIs to administrators",
            "Add pagination, search, and board relation",
        ],
    }


def create_application(
    db: Session, info: ColumnApplicationCreate
) -> ColumnApplicationInfo:
    app = ColumnApplication(
        user_id=info.user_id,
        title=info.title,
        description=info.description,
        reason=info.reason,
    )
    db.add(app)
    db.flush()
    db.refresh(app)
    return _app_to_schema(app)


def list_applications(db: Session) -> list[ColumnApplicationInfo]:
    apps = (
        db.query(ColumnApplication)
        .order_by(ColumnApplication.id.desc())
        .all()
    )
    return [_app_to_schema(a) for a in apps] # type: ignore[return-value]


def get_application(db: Session, application_id: int) -> ColumnApplicationInfo:
    app = db.query(ColumnApplication).filter(ColumnApplication.id == application_id).first()
    if not app:
        raise BizError(ErrCode.COLUMN_APPLICATION_NOT_FOUND)
    return _app_to_schema(app) # type: ignore[return-value]


def review_application(
    db: Session, application_id: int, info: ColumnApplicationReview
) -> dict:
    app = db.query(ColumnApplication).filter(ColumnApplication.id == application_id).first()
    if not app:
        raise BizError(ErrCode.COLUMN_APPLICATION_NOT_FOUND)

    app.status = info.status
    app.reviewer_id = info.reviewer_id
    app.review_note = info.review_note
    app.reviewed_at = _now()
    db.flush()
    db.refresh(app)

    column = None
    if info.status == ColumnApplicationStatus.APPROVED:
        column = _ensure_column_for_application(db, app) # type: ignore[return-value]

    return {
        "application": _app_to_schema(app).model_dump(), # type: ignore[return-value]
        "column": column.model_dump() if column else None,
    }


def list_columns(db: Session) -> list[ColumnInfo]:
    cols = db.query(Column).order_by(Column.id.desc()).all()
    return [_col_to_schema(c) for c in cols] # type: ignore[return-value]


def get_column(db: Session, column_id: int) -> ColumnInfo:
    col = db.query(Column).filter(Column.id == column_id).first()
    if not col:
        raise BizError(ErrCode.COLUMN_NOT_FOUND)
    return _col_to_schema(col) # type: ignore[return-value]


def create_post(
    db: Session, column_id: int, info: ColumnPostCreate
) -> ColumnPostInfo:
    col = db.query(Column).filter(Column.id == column_id).first()
    if not col:
        raise BizError(ErrCode.COLUMN_NOT_FOUND)

    post = ColumnPost(
        column_id=column_id,
        author_id=info.author_id,
        title=info.title,
        summary=info.summary,
        content=info.content,
        status=ColumnPostStatus.PUBLISHED,
        published_at=_now(),
    )
    db.add(post)
    db.flush()
    db.refresh(post)
    return _post_to_schema(post)


def list_posts(db: Session, column_id: int) -> list[ColumnPostInfo]:
    col = db.query(Column).filter(Column.id == column_id).first()
    if not col:
        raise BizError(ErrCode.COLUMN_NOT_FOUND)
    posts = (
        db.query(ColumnPost)
        .filter(ColumnPost.column_id == column_id)
        .order_by(ColumnPost.id.desc())
        .all()
    )
    return [_post_to_schema(p) for p in posts] # type: ignore[arg-type]


def get_post(
    db: Session, post_id: int, column_id: int | None = None
) -> ColumnPostInfo:
    filters = [ColumnPost.id == post_id]
    if column_id is not None:
        filters.append(ColumnPost.column_id == column_id) # type: ignore[arg-type]
    post = db.query(ColumnPost).filter(and_(*filters)).first()
    if not post:
        raise BizError(ErrCode.COLUMN_POST_NOT_FOUND)
    return _post_to_schema(post) # type: ignore[arg-type]


def _ensure_column_for_application(
    db: Session, application: ColumnApplication
) -> ColumnInfo:
    col = (
        db.query(Column)
        .filter(Column.application_id == application.id)
        .first()
    )
    if col:
        return _col_to_schema(col) # type: ignore[arg-type]

    col = Column(
        owner_id=application.user_id,
        application_id=application.id,
        title=application.title,
        description=application.description,
    )
    db.add(col)
    db.flush()
    db.refresh(col)
    return _col_to_schema(col)