from pathlib import Path

from linqex import Enumerable
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import UserStorageItem

REFER_CACHE = dict[str,int]()


def build_refer_cache(db: Session) -> None:
    # 读取硬盘拿到所有哈希
    storage_path = Path(settings.files_store_dir)
    if not storage_path.exists():
        return None
    all_files = (
        (Enumerable(storage_path.rglob("*")))
            .where(lambda x: x.is_file())
            .to_list()
    )
    for file in all_files:
        full_path = str(file)
        hash_value = file.name
        stmt = select(func.count()).where(UserStorageItem.actual_path == full_path)
        count = db.scalar(stmt) or 0
        if not count:
            file.unlink(missing_ok=True)
            continue
        REFER_CACHE[hash_value] = count
    return None
