"""文件上传、列表、审核、删除路由。"""

import shutil
from datetime import datetime
from hashlib import sha3_256
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Annotated, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import UserStorageItem
from app.db.session import get_session
from app.modules.auth.deps import CurrentUser, get_current_user
from app.modules.common import ApiResp, ListData
from app.modules.files.models import FileStatus
from app.modules.files.schemas import FileInfo
from app.modules.files.service import REFER_CACHE

router = APIRouter(prefix="/files", tags=["files"])

FILE_MAX_SIZE = settings.max_upload_bytes
BLOCK_SIZE = 1 << 20  # 1 MiB


def _load_meta(item: UserStorageItem) -> FileInfo:
    return FileInfo.model_validate(item.file_metadata)


def _dump_meta(meta: FileInfo) -> FileInfo:
    return cast("FileInfo", meta.model_dump(mode="json"))


def _hash_of(actual_path: str) -> str:
    return Path(actual_path).name


def _decref(actual_path: str) -> None:
    key = _hash_of(actual_path)
    if key not in REFER_CACHE:
        return
    REFER_CACHE[key] -= 1
    if REFER_CACHE[key] <= 0:
        REFER_CACHE.pop(key, None)
        Path(actual_path).unlink(missing_ok=True)


@router.post("/upload")
def upload_files(
    file: Annotated[UploadFile, File(...)],
    cur: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
    target_path: Annotated[str, Form()] = "",
    category_id: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "[]",
) -> ApiResp[FileInfo]:
    """上传文件：流式计算 sha3、校验大小、去重落盘、入库（同 showed_path 则替换）。"""
    spooled = cast(SpooledTemporaryFile, cast(object, file.file))
    sha3_hash = sha3_256()
    file_size = 0
    while True:
        chunk = spooled.read(BLOCK_SIZE)
        if not chunk:
            break
        sha3_hash.update(chunk)
        file_size += len(chunk)
        if file_size > FILE_MAX_SIZE:
            raise HTTPException(status_code=413, detail="File exceeds max size")

    hash_string = sha3_hash.hexdigest()
    file_storage_path = Path(settings.files_store_dir) / hash_string[:4] / hash_string
    file_storage_path.parent.mkdir(parents=True, exist_ok=True)

    # 去重：同哈希文件已存在就不重复落盘
    if not file_storage_path.exists():
        spooled.rollover()  # 内存内容滚到磁盘临时文件，确保 .name 可用
        shutil.move(spooled.name, str(file_storage_path))

    showed_path = f"{target_path}/{file.filename or ''}".strip("/")

    metadata = FileInfo(
        original_name=target_path,
        uploader_id=cur.id,
        mime_type=file.content_type or "",
        size=file_size,
        category_id=category_id,
        status=FileStatus.PENDING,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        description=description,
        tags=tags,
        download_count=0,
        view_count=0,
    )

    existing = db.execute(
        select(UserStorageItem).where(UserStorageItem.showed_path == showed_path)
    ).scalar()

    if existing:
        # 替换：先回收旧物理文件的引用，再指向新文件
        _decref(existing.actual_path)
        existing.actual_path = str(file_storage_path)
        metadata.item_id = existing.id
        existing.file_metadata = _dump_meta(metadata)
    else:
        new_item = UserStorageItem(
            owner_id=cur.id,
            actual_path=str(file_storage_path),
            file_metadata=_dump_meta(metadata),
        )
        db.add(new_item)
        db.flush()  # 触发自增主键，拿到 new_item.id
        metadata.item_id = new_item.id
        new_item.file_metadata = _dump_meta(metadata)

    REFER_CACHE[hash_string] += 1
    db.commit()
    return ApiResp[FileInfo](code=200, msg="success", data=metadata)


@router.get("/ls")
def get_file_under_user(
    cur: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
) -> ApiResp[ListData[FileInfo]]:
    """列出当前用户的所有文件。"""
    items = db.query(UserStorageItem).filter(UserStorageItem.owner_id == cur.id).all()
    return ApiResp[ListData[FileInfo]](
        code=200,
        msg="success",
        data=ListData[FileInfo](items=[_load_meta(item) for item in items]),
    )


@router.get("/review")
def review_file(
    cur: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
    target_item_id: Annotated[int, Query(gt=0)],
    target_status: Annotated[str, Query()],
) -> ApiResp[FileInfo]:
    """管理员审核文件：通过 / 驳回（驳回时删除物理文件并联动同 hash 的其他条目）。"""
    if cur.account_level != "admin":
        raise HTTPException(status_code=403, detail="Only admin can review files")
    if target_status not in (FileStatus.APPROVED, FileStatus.REJECTED):
        raise HTTPException(status_code=400, detail="Invalid status")

    item = db.get(UserStorageItem, target_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    meta = _load_meta(item)
    if meta.status != FileStatus.PENDING:
        raise HTTPException(status_code=400, detail="Item status is not pending")
    meta.status = target_status
    item.file_metadata = _dump_meta(meta)

    if target_status == FileStatus.REJECTED:
        # 同一物理文件被多个 item 引用：一并标记 REJECTED，并删除物理文件
        item_hash = _hash_of(item.actual_path)
        others = db.execute(
            select(UserStorageItem).where(UserStorageItem.actual_path == item.actual_path)
        ).scalars().all()
        for other in others:
            other_meta = _load_meta(other)
            other_meta.status = FileStatus.REJECTED
            other.file_metadata = _dump_meta(other_meta)
        REFER_CACHE.pop(item_hash, None)
        Path(item.actual_path).unlink(missing_ok=True)

    db.commit()
    return ApiResp[FileInfo](
        code=200,
        msg=f"Item {target_item_id} status {target_status}",
        data=meta,
    )


@router.post("/remove")
def remove_file(
    cur: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
    target_item_id: Annotated[int, Form(gt=0)],
) -> ApiResp[FileInfo]:
    """删除文件（软删除）：管理员或文件所有者可操作，引用归零时清理物理文件。"""
    item = db.get(UserStorageItem, target_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    if cur.account_level != "admin" and cur.id != item.owner_id:
        raise HTTPException(status_code=403, detail="You are not the owner of this file")

    _decref(item.actual_path)

    meta = _load_meta(item)
    meta.status = FileStatus.DELETED
    item.file_metadata = _dump_meta(meta)
    db.commit()
    return ApiResp[FileInfo](
        code=200,
        msg=f"Item {target_item_id} deleted",
        data=meta,
    )
