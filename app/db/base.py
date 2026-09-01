"""数据库声明基座：Base / UTCDateTime / 时间辅助函数。

跨模块共享的 ORM 基础设施集中于此（计划 §2 db/base.py）。各模块 ``models.py``
从本模块 import ``Base``/``UTCDateTime``/``now_iso``/``expires_at``。本模块不依赖任何
业务模块，保证 ``core/``、``db/`` 层不反向依赖业务（import-linter 契约）。

注意：必须确保全部模块 ``models.py`` 都被导入后 SQLAlchemy 的 mapper registry
才会在 ``configure()`` 时解析到所有 relationship 字符串引用（见 db/registry 侧的
模型预注册）。
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import DateTime, TypeDecorator
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeEngine


class Base(DeclarativeBase):
    pass


def now_iso() -> datetime.datetime:
    """当前 UTC 时间（timezone-aware），用于默认值与比较。"""
    return datetime.datetime.now(datetime.UTC)


def expires_at(days: float = 0, minutes: float = 0) -> datetime.datetime:
    """从现在起 days/minutes 后的 UTC 时间（timezone-aware）。"""
    return datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        days=days, minutes=minutes
    )


class UTCDateTime(TypeDecorator[datetime.datetime]):
    """带时区的 UTC 时间列类型。底层使用 DateTime(timezone=True)"""

    impl: TypeEngine[Any] | type[TypeEngine[Any]] = DateTime(timezone=True)
    cache_ok: bool | None = True

    def process_result_value(
        self, value: datetime.datetime | None, dialect: Dialect
    ) -> datetime.datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=datetime.UTC)
        return value
