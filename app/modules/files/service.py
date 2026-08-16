import asyncio
import hashlib
import json
import uuid
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.err import BizError
from app.db.models import LibraryFile, User
from app.db.repo import get_or_raise
from app.modules.files.errors import FileErr
from app.modules.files.models import FILES_TABLE_PLAN, FileStatus
from app.modules.files.schemas import FileCreate, FileInfo, PageData


class _Readable(Protocol):
    """可同步分块读取的 file-like 对象最小协议。"""

    def read(self, size: int = -1, /) -> bytes: ...


def get_files_plan() -> dict[str, Any]:
    return {
        "status": "implemented_minimal",
        "tables": FILES_TABLE_PLAN,
        "next_steps": [
            "Add review approval workflow",
            "Add duplicate / plagiarism detection",
            "Add file serving with presigned URL",
        ],
    }


def _uploader_name(user: User) -> str:
    if user.profile and user.profile.nickname:
        return user.profile.nickname
    return user.username


def _file_to_schema(f: LibraryFile, uploader_name: str) -> FileInfo:
    return FileInfo.model_validate(f).model_copy(
        update={"uploader_name": uploader_name}
    )


async def _uploader_map(db: AsyncSession, user_ids: list[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    result = await db.execute(
        select(User)
        .where(User.id.in_(set(user_ids)))
        .options(selectinload(User.profile))
    )
    users = result.scalars().all()
    return {u.id: _uploader_name(u) for u in users}


async def list_files(
    db: AsyncSession,
    page: int = 1,
    limit: int = 20,
    category_id: str | None = None,
    status: str | None = None,
    sort: str = "newest",
) -> PageData[FileInfo]:
    base = select(LibraryFile)
    if category_id:
        base = base.where(LibraryFile.category_id == category_id)
    if status:
        base = base.where(LibraryFile.status == status)

    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    order = (
        LibraryFile.download_count.desc()
        if sort == "downloads"
        else LibraryFile.id.desc()
    )
    files = (
        (await db.execute(base.order_by(order).offset((page - 1) * limit).limit(limit)))
        .scalars()
        .all()
    )

    names = await _uploader_map(db, [f.uploader_id for f in files])
    items = [_file_to_schema(f, names.get(f.uploader_id, "")) for f in files]
    return PageData(
        items=items, total=total, page=page, pages=(total + limit - 1) // limit
    )


async def get_file(db: AsyncSession, file_id: int, bump_view: bool = False) -> FileInfo:
    f = await get_or_raise(
        db, LibraryFile, FileErr.NOT_FOUND, LibraryFile.id == file_id
    )

    if bump_view:
        f.view_count += 1
        await db.flush()

    names = await _uploader_map(db, [f.uploader_id])
    return _file_to_schema(f, names.get(f.uploader_id, ""))


_CHUNK = 1024 * 1024  # 分块读写，避免整文件载入内存


def _stream_to_disk_hash(
    stream: _Readable, dest_path: Path, limit: int
) -> tuple[int, str]:
    """
    同步分块读取 ``stream`` 写盘并流式计算 SHA3-256，返回 ``(总字节数, 哈希 hex)``。
    在 async 端点内通过 asyncio.to_thread 调度，避免文件读写（含建目录）阻塞事件循环。
    超过 ``limit`` 抛 ``FILE_TOO_LARGE``；OS 错误抛 ``FileErr.STORE_ERROR``。
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha3_256()
    total = 0
    with dest_path.open("wb") as out:
        while True:
            chunk = stream.read(_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise BizError(
                    FileErr.TOO_LARGE,
                    detail=f"Upload exceeds {limit} byte limit",
                )
            hasher.update(chunk)
            out.write(chunk)
    return total, hasher.hexdigest()


async def _write_upload(stream: _Readable, dest: Path, limit: int) -> tuple[int, str]:
    try:
        return await asyncio.to_thread(_stream_to_disk_hash, stream, dest, limit)
    except OSError as exc:
        await asyncio.to_thread(dest.unlink, missing_ok=True)
        raise BizError(
            FileErr.STORE_ERROR, detail=f"Failed to store file: {exc}"
        ) from exc


def _content_path(sha3_hash: str) -> Path:
    """内容寻址落盘路径：``files_store_dir/<hash>``，同内容同路径，天然去重。"""
    return Path(settings.files_store_dir) / sha3_hash


def _make_stored_name(original_name: str) -> str:
    """生成唯一展示/定位名（存储层按内容哈希去重、共享物理文件，此名仅唯一）。"""
    suffix = Path(original_name).suffix[:32]
    return f"{uuid.uuid4().hex}{suffix}"


def _physical_location(f: LibraryFile) -> Path | None:
    """该条目引用物理文件的磁盘路径：优先 storage_path，兼容旧数据按 stored_name 推断。"""
    if f.storage_path:
        return Path(f.storage_path)
    return None


async def _refer_count(db: AsyncSession, sha3_hash: str) -> int:
    """统计引用该物理文件（同 sha3_hash）的条目数。DB 聚合，持久化且天然一致。"""
    return (
        await db.scalar(
            select(func.count())
            .select_from(LibraryFile)
            .where(LibraryFile.sha3_hash == sha3_hash)
        )
        or 0
    )


async def _sync_ref_count(db: AsyncSession, sha3_hash: str) -> None:
    """把全局引用计数写回该哈希对应的所有条目，保证 ref_count 列不漂移。"""
    if not sha3_hash:
        return
    count = await _refer_count(db, sha3_hash)
    rows = (
        (
            await db.execute(
                select(LibraryFile).where(LibraryFile.sha3_hash == sha3_hash)
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.ref_count = count


def _new_temp_file() -> Path:
    """在存储目录下建一个安全命名的临时文件，避免原文件名中的路径穿越。

    需 `delete=False` 并在拿到 `.name` 后立即关闭，交由调用方决定 move/删除，
    不能走 context manager（会提前删文件）。存储根目录不可写时抛 ``STORE_ERROR``。
    """
    try:
        tmp = NamedTemporaryFile(  # noqa: SIM115
            dir=settings.files_store_dir, suffix=".tmp", delete=False
        )
    except OSError as exc:
        raise BizError(
            FileErr.STORE_ERROR, detail=f"Failed to store file: {exc}"
        ) from exc
    path = Path(tmp.name)
    tmp.close()
    return path


async def create_file(
    db: AsyncSession,
    uploader_id: int,
    info: FileCreate,
    stream: _Readable,
    max_bytes: int | None = None,
) -> FileInfo:
    """把上传流分块落盘（内容寻址去重）并登记元数据。

    ``stream`` 需提供 ``read(n)``（可同步 File 对象）。累计超过 ``max_bytes``（默认取配置值）
    立即中止并抛 ``FILE_TOO_LARGE``，不留下磁盘临时文件。落盘在后台线程执行，避免阻塞事件循环。

    内容寻址：流式计算 SHA3-256，同一内容只物理落盘一份；重复上传仅新增元数据条目并
    共享同一物理文件，引用计数（ref_count）持久化在 DB，供删除/清理断言。
    """
    limit = max_bytes or settings.max_upload_bytes
    temp = _new_temp_file()
    final: Path | None = None
    content_hash = ""
    try:
        total, content_hash = await _write_upload(stream, temp, limit)
        final = _content_path(content_hash)
        final.parent.mkdir(parents=True, exist_ok=True)
        # 同内容已存在：复用物理文件，丢弃临时文件；否则 move 为正式文件。
        if final.exists():
            await asyncio.to_thread(temp.unlink, missing_ok=True)
        else:
            await asyncio.to_thread(temp.replace, final)
    except BizError:
        await asyncio.to_thread(temp.unlink, missing_ok=True)
        raise
    except Exception:
        await asyncio.to_thread(temp.unlink, missing_ok=True)
        if final is not None:
            await asyncio.to_thread(final.unlink, missing_ok=True)
        raise

    try:
        f = LibraryFile(
            uploader_id=uploader_id,
            original_name=info.original_name,
            stored_name=_make_stored_name(info.original_name),
            sha3_hash=content_hash,
            ref_count=1,
            storage_path=str(final),
            mime_type=info.mime_type,
            size=total,
            category_id=info.category_id,
            description=info.description,
            tags=json.dumps(info.tags, ensure_ascii=False),
        )
        db.add(f)
        await db.flush()
        await _sync_ref_count(db, content_hash)
        await db.flush()
    except Exception:
        # 入库失败：仅当物理文件在本次是唯一引用（无其他条目）时才回收磁盘。
        if final is not None and await _refer_count(db, content_hash) <= 1:
            await asyncio.to_thread(final.unlink, missing_ok=True)
        raise

    names = await _uploader_map(db, [f.uploader_id])
    return _file_to_schema(f, names.get(f.uploader_id, ""))


async def bump_download(db: AsyncSession, file_id: int) -> int:
    f = await get_or_raise(
        db, LibraryFile, FileErr.NOT_FOUND, LibraryFile.id == file_id
    )
    f.download_count += 1
    await db.flush()
    return f.download_count


async def review_file(
    db: AsyncSession,
    file_id: int,
    target_status: FileStatus,
    review_comment: str | None = None,
    is_admin: bool = False,
) -> FileInfo:
    """管理员审核文件：通过 / 驳回（驳回时删除物理文件并联动同 hash 条目置 REJECTED）。"""
    if not is_admin:
        raise BizError(FileErr.STORE_ERROR, detail="Only admin can review files")
    if target_status not in (FileStatus.APPROVED, FileStatus.REJECTED):
        raise BizError(FileErr.INVALID_STATUS, detail="Invalid review status")

    f = await get_or_raise(
        db, LibraryFile, FileErr.NOT_FOUND, LibraryFile.id == file_id
    )
    if f.status != FileStatus.PENDING:
        raise BizError(FileErr.NOT_PENDING, detail="File is not pending")

    f.status = target_status
    f.review_comment = review_comment

    if target_status == FileStatus.REJECTED and f.sha3_hash:
        # 同一物理文件被多个条目引用：一并标记 REJECTED，并删除物理文件。
        same_hash = (
            (
                await db.execute(
                    select(LibraryFile).where(LibraryFile.sha3_hash == f.sha3_hash)
                )
            )
            .scalars()
            .all()
        )
        for other in same_hash:
            other.status = FileStatus.REJECTED
            other.review_comment = other.review_comment or review_comment
        await db.flush()
        physical = _physical_location(f)
        if physical is not None:
            await asyncio.to_thread(physical.unlink, missing_ok=True)
    else:
        await db.flush()

    names = await _uploader_map(db, [f.uploader_id])
    return _file_to_schema(f, names.get(f.uploader_id, ""))


async def delete_file(
    db: AsyncSession,
    file_id: int,
    actor_id: int,
    is_admin: bool = False,
) -> FileInfo:
    """软删除文件：管理员或文件所有者可操作，物理文件引用归零时清理磁盘。"""
    f = await get_or_raise(
        db, LibraryFile, FileErr.NOT_FOUND, LibraryFile.id == file_id
    )
    if not is_admin and f.uploader_id != actor_id:
        raise BizError(FileErr.STORE_ERROR, detail="Not the owner of this file")

    old_hash = f.sha3_hash
    f.status = FileStatus.DELETED
    await db.flush()

    if old_hash:
        remaining = (
            await db.scalar(
                select(func.count())
                .select_from(LibraryFile)
                .where(
                    LibraryFile.sha3_hash == old_hash,
                    LibraryFile.status != FileStatus.DELETED,
                )
            )
            or 0
        )
        await _sync_ref_count(db, old_hash)
        # 引用全部删除 → 物理文件无引用，清理磁盘。
        physical = _physical_location(f)
        if remaining <= 0 and physical is not None:
            await asyncio.to_thread(physical.unlink, missing_ok=True)

    names = await _uploader_map(db, [f.uploader_id])
    return _file_to_schema(f, names.get(f.uploader_id, ""))
