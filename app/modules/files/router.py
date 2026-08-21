import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import respond
from app.db.session import get_read_session, get_session
from app.modules.auth.deps import CurrentUser, get_current_user
from app.modules.common import ApiResp, ModuleStatus, PageData
from app.modules.files.models import FileStatus
from app.modules.files.schemas import (
    DownloadUrlInfo,
    FileCreate,
    FileInfo,
    UploadInitResp,
)
from app.modules.files.service import (
    bump_download,
    confirm_upload,
    delete_file,
    download_url,
    get_file,
    get_files_plan,
    list_files,
    review_file,
    serve_content,
    upload_init,
)
from app.modules.files.service import (
    create_file as create_file_service,
)

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/status", response_model=ModuleStatus)
async def files_status() -> ModuleStatus:
    return ModuleStatus(
        module="files",
        status="implemented_minimal",
        responsibility="Manage shared academic files and downloads.",
        next_steps=get_files_plan()["next_steps"],
    )


@router.get("", response_model=ApiResp[PageData[FileInfo]])
@respond
async def get_files(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category_id: str | None = Query(default=None, max_length=50),
    status: str | None = Query(default=None, max_length=20),
    sort: str = Query(default="newest"),
    db: AsyncSession = Depends(get_read_session),
) -> PageData[FileInfo]:
    return await list_files(
        db, page=page, limit=limit, category_id=category_id, status=status, sort=sort
    )


@router.post("", response_model=ApiResp[FileInfo])
@respond
async def upload_file(
    file: UploadFile = File(...),
    category_id: str = Form(default=""),
    description: str = Form(default=""),
    tags: str = Form(default="[]"),
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> FileInfo:
    try:
        tags_list: list[str] = json.loads(tags) if tags else []
    except json.JSONDecodeError:
        tags_list = []

    info = FileCreate(
        original_name=file.filename or "untitled",
        mime_type=file.content_type or "application/octet-stream",
        category_id=category_id,
        description=description,
        tags=tags_list,
    )
    return await create_file_service(db, cur.id, info, file.file)


@router.post("/upload-init", response_model=ApiResp[UploadInitResp])
@respond
async def upload_init_endpoint(
    payload: FileCreate,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> UploadInitResp:
    """预签名直传初始化：Local→sync，S3→direct（presigned PUT + upload_id）。"""
    return await upload_init(db, payload, cur)


@router.post("/{upload_id}/confirm", response_model=ApiResp[FileInfo])
@respond
async def confirm_upload_endpoint(
    upload_id: str,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> FileInfo:
    """确认直传：回读对象→SHA3→去重→登记 PENDING。upload_id 为 str UUID。"""
    return await confirm_upload(db, upload_id, cur)


@router.get("/{file_id}", response_model=ApiResp[FileInfo])
@respond
async def get_file_detail(
    file_id: int, db: AsyncSession = Depends(get_session)
) -> FileInfo:
    return await get_file(db, file_id, bump_view=True)


@router.post("/{file_id}/download", response_model=ApiResp[dict[str, Any]])
@respond
async def download_file(
    file_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return {"download_count": await bump_download(db, file_id)}


@router.post("/{file_id}/review", response_model=ApiResp[FileInfo])
@respond
async def review_uploaded_file(
    file_id: int,
    status: FileStatus = Form(...),
    review_comment: str | None = Form(default=None),
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> FileInfo:
    """管理员审核文件：通过 / 驳回（驳回时删除物理文件并联动同 hash 条目）。"""
    return await review_file(
        db,
        file_id,
        target_status=status,
        review_comment=review_comment,
        is_admin=cur.account_level == "admin",
    )


@router.post("/{file_id}/delete", response_model=ApiResp[FileInfo])
@respond
async def delete_uploaded_file(
    file_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> FileInfo:
    """软删除文件：管理员或文件所有者可操作，引用归零时清理磁盘。"""
    return await delete_file(
        db,
        file_id,
        actor_id=cur.id,
        is_admin=cur.account_level == "admin",
    )


@router.get("/{file_id}/preview")
async def preview_file(
    file_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """预览：仅 APPROVED 可访问，inline 流式返回，计 view_count。"""
    return await serve_content(db, file_id, "inline")


@router.get("/{file_id}/download/url", response_model=ApiResp[DownloadUrlInfo])
@respond
async def download_file_url(
    file_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> DownloadUrlInfo:
    """签发下载 URL（本地→/content、S3→预签名），计 download_count。"""
    return await download_url(db, file_id, cur)


@router.get("/{file_id}/content")
async def download_file_content(
    file_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """附件流式下载：仅 APPROVED 可访问。"""
    return await serve_content(db, file_id, "attachment")
