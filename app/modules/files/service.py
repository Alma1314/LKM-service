import queue
import re
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue
from typing import Deque

from linqex import Enumerable
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import UserStorageItem

REFER_CACHE = dict[str, int]()


def build_refer_cache(db: Session) -> None:
    # 读取硬盘拿到所有哈希
    storage_path = Path(settings.files_store_dir)
    if not storage_path.exists():
        return None
    all_files = (Enumerable(storage_path.rglob("*"))).where(lambda x: x.is_file()).to_list()
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


class FileAccessRecord:
    user_id: int
    item_id: int
    timestamp: datetime


class FileAccessRateLimiter:
    _access_cache: dict[int, deque[FileAccessRecord]]

    def add_record(self, record: FileAccessRecord):
        if record.item_id not in self._access_cache:
            self._access_cache[record.item_id] = deque()

        while self._access_cache[record.item_id] and self._access_cache[record.item_id][
            0
        ].timestamp < record.timestamp - timedelta(days=1):
            self._access_cache[record.item_id].popleft()

        self._access_cache[record.item_id].append(record)

    def check_access(self, item_id: int, permission: tuple[str, str]) -> bool:
        if item_id not in self._access_cache:
            return True

        count = (Enumerable(self._access_cache[item_id])).count()
        match permission:
            case ("local", "member"):
                return count <= 1
            case ("normal", "member"):
                return count <= 10
            case ("normal", "columnist"):
                return count <= 20
            case ("normal", "author"):
                return count <= 40
            case ("admin", _):
                return True
        return False

limiter = FileAccessRateLimiter()
