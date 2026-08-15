import shutil
from datetime import datetime
from hashlib import sha3_256
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Annotated, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import UserStorageItem
from app.db.session import get_session
from app.modules.auth.deps import CurrentUser, get_current_user
from app.modules.common import ApiResp, ListData
from app.modules.files.models import FileStatus
from app.modules.files.schemas import FileInfo

router = APIRouter(prefix="/files", tags=["files"])

FILE_MAX_SIZE = 20 * 1 << 30  # 20GB
BLOCK_SIZE = 1 << 20  # 1MB


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
    """
    上传文件，顺便算好sha3，然后落盘
    """
    sha3_hash = sha3_256()
    file_size = 0
    spooled = cast(SpooledTemporaryFile, cast(object, file.file))
    while True:
        chunk = spooled.read(BLOCK_SIZE)
        if not chunk:
            break
        sha3_hash.update(chunk)
        file_size += len(chunk)
        if file_size > FILE_MAX_SIZE:
            raise HTTPException(status_code=413, detail="File Exceed MAX File size 20GB")
    hash_string = sha3_hash.hexdigest()
    file_storage_path = Path(settings.files_store_dir) / hash_string[0:4] / hash_string
    file_storage_path.parent.mkdir(parents=True, exist_ok=True)

    # 当同hash文件不存在再落盘
    if not file_storage_path.exists():
        if file_size <= BLOCK_SIZE:
            spooled.rollover()
        shutil.move(spooled.name, str(file_storage_path))

    # 入库
    metadata = FileInfo(
        original_name=target_path,
        uploader_id=cur.id,
        mime_type=file.content_type if file.content_type else "",
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
    item = UserStorageItem(
        owner_id=cur.id, showed_path=target_path, actual_path=str(file_storage_path), file_metadata=metadata
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return ApiResp[FileInfo](code=200, msg="success", data=metadata)


@router.get("/ls")
def get_file_under_folder(
    cur: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
    target_path: Annotated[str, Form()] = "",
) -> ApiResp[ListData[FileInfo]]:
    """
    获取文件夹下的所有文件
    """
    items = db.query(UserStorageItem).filter(
        UserStorageItem.owner_id == cur.id,
        UserStorageItem.showed_path.startswith(target_path),
    ).all()
    return ApiResp[ListData[FileInfo]](
        code=200, msg="success", data=ListData[FileInfo](items=[item.file_metadata for item in items])
    )

