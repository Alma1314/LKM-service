from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.err import BizError, ErrCode, respond
from app.db.session import get_session
from app.modules.auth.deps import CurrentUser, get_current_user
from app.modules.columns.schemas import (
    ColumnApplicationCreate,
    ColumnApplicationInfo,
    ColumnApplicationReview,
    ColumnInfo,
    ColumnPlanData,
    ColumnPostCreate,
    ColumnPostInfo,
    ReviewResultData,
)
from app.modules.columns.service import (
    create_application,
    create_post,
    get_application,
    get_column,
    get_column_plan,
    get_post,
    list_applications,
    list_columns,
    list_posts,
    review_application,
)
from app.modules.common import ApiResp, ListData, ModuleStatus

router = APIRouter(prefix="/columns", tags=["columns"])


@router.get("/status", response_model=ModuleStatus)
def columns_status() -> ModuleStatus:
    return ModuleStatus(
        module="columns",
        status="implemented_minimal",
        responsibility="Handle column applications, approved columns, and column posts.",
        next_steps=[
            "Add authentication before write operations",
            "Restrict review APIs to administrators",
            "Add pagination, search, and board relation",
        ],
    )


@router.get("/plan", response_model=ApiResp[ColumnPlanData])
@respond
def column_plan():
    return get_column_plan()


@router.post("/applications", response_model=ApiResp[ColumnApplicationInfo])
@respond
def apply_column(
    info: ColumnApplicationCreate,
    cur: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    if cur.id != info.user_id:
        raise BizError(ErrCode.FORBIDDEN)
    application = create_application(db, info)
    return application.model_dump()


@router.get("/applications", response_model=ApiResp[ListData[ColumnApplicationInfo]])
@respond
def get_applications(db: Session = Depends(get_session)):
    applications = list_applications(db)
    return {"items": [item.model_dump() for item in applications]}


@router.get("/applications/{application_id}", response_model=ApiResp[ColumnApplicationInfo])
@respond
def get_application_detail(application_id: int, db: Session = Depends(get_session)):
    application = get_application(db, application_id)
    return application.model_dump()


@router.post("/applications/{application_id}/review", response_model=ApiResp[ReviewResultData])
@respond
def review_column_application(
    application_id: int,
    info: ColumnApplicationReview,
    cur: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    if cur.id != info.reviewer_id:
        raise BizError(ErrCode.FORBIDDEN)
    return review_application(db, application_id, info)


@router.get("", response_model=ApiResp[ListData[ColumnInfo]])
@respond
def get_columns(db: Session = Depends(get_session)):
    columns = list_columns(db)
    return {"items": [item.model_dump() for item in columns]}


@router.get("/{column_id}", response_model=ApiResp[ColumnInfo])
@respond
def get_column_detail(column_id: int, db: Session = Depends(get_session)):
    column = get_column(db, column_id)
    return column.model_dump()


@router.post("/{column_id}/posts", response_model=ApiResp[ColumnPostInfo])
@respond
def publish_column_post(
    column_id: int,
    info: ColumnPostCreate,
    cur: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    if cur.id != info.author_id:
        raise BizError(ErrCode.FORBIDDEN)
    post = create_post(db, column_id, info)
    return post.model_dump()


@router.get("/{column_id}/posts", response_model=ApiResp[ListData[ColumnPostInfo]])
@respond
def get_column_posts(column_id: int, db: Session = Depends(get_session)):
    posts = list_posts(db, column_id)
    return {"items": [item.model_dump() for item in posts]}


@router.get("/{column_id}/posts/{post_id}", response_model=ApiResp[ColumnPostInfo])
@respond
def get_column_post_detail(column_id: int, post_id: int, db: Session = Depends(get_session)):
    post = get_post(db, post_id, column_id=column_id)
    return post.model_dump()
