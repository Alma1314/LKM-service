from fastapi import APIRouter

from app.core.err import respond
from app.db.session import getdb
from app.modules.columns.schemas import (
    ColumnApplicationCreate,
    ColumnApplicationReview,
    ColumnPostCreate,
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
from app.modules.common import ApiResp, ModuleStatus

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


@router.get("/plan", response_model=ApiResp)
@respond
def column_plan():
    return get_column_plan()


@router.post("/applications", response_model=ApiResp)
@respond
def apply_column(info: ColumnApplicationCreate):
    with getdb() as conn:
        application = create_application(conn, info)
    return application.model_dump()


@router.get("/applications", response_model=ApiResp)
@respond
def get_applications():
    with getdb() as conn:
        applications = list_applications(conn)
    return {"items": [item.model_dump() for item in applications]}


@router.get("/applications/{application_id}", response_model=ApiResp)
@respond
def get_application_detail(application_id: int):
    with getdb() as conn:
        application = get_application(conn, application_id)
    return application.model_dump()


@router.post("/applications/{application_id}/review", response_model=ApiResp)
@respond
def review_column_application(application_id: int, info: ColumnApplicationReview):
    with getdb() as conn:
        return review_application(conn, application_id, info)


@router.get("", response_model=ApiResp)
@respond
def get_columns():
    with getdb() as conn:
        columns = list_columns(conn)
    return {"items": [item.model_dump() for item in columns]}


@router.get("/{column_id}", response_model=ApiResp)
@respond
def get_column_detail(column_id: int):
    with getdb() as conn:
        column = get_column(conn, column_id)
    return column.model_dump()


@router.post("/{column_id}/posts", response_model=ApiResp)
@respond
def publish_column_post(column_id: int, info: ColumnPostCreate):
    with getdb() as conn:
        post = create_post(conn, column_id, info)
    return post.model_dump()


@router.get("/{column_id}/posts", response_model=ApiResp)
@respond
def get_column_posts(column_id: int):
    with getdb() as conn:
        posts = list_posts(conn, column_id)
    return {"items": [item.model_dump() for item in posts]}


@router.get("/{column_id}/posts/{post_id}", response_model=ApiResp)
@respond
def get_column_post_detail(column_id: int, post_id: int):
    with getdb() as conn:
        post = get_post(conn, post_id, column_id=column_id)
    return post.model_dump()
