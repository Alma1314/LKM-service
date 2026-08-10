import json

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import respond
from app.db.session import get_session
from app.modules.auth.deps import CurrentUser, get_current_user
from app.modules.common import ApiResp, ModuleStatus
from app.modules.files.schemas import FileCreate, FileInfo, PageData
from app.modules.files.service import (
    bump_download,
    create_file as create_file_service,
    get_file,
    get_files_plan,
    list_files,
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
    db: AsyncSession = Depends(get_session),
):
    return await list_files(db, page=page, limit=limit, category_id=category_id, status=status, sort=sort)


@router.post("", response_model=ApiResp[FileInfo])
@respond
async def upload_file(
    file: UploadFile = File(...),
    category_id: str = Form(default=""),
    description: str = Form(default=""),
    tags: str = Form(default="[]"),
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    try:
        tags_list = json.loads(tags) if tags else []
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


@router.get("/{file_id}", response_model=ApiResp[FileInfo])
@respond
async def get_file_detail(file_id: int, db: AsyncSession = Depends(get_session)):
    return await get_file(db, file_id, bump_view=True)


@router.post("/{file_id}/download", response_model=ApiResp[dict])
@respond
async def download_file(
    file_id: int,
    cur: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    return {"download_count": await bump_download(db, file_id)}
