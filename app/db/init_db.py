"""数据库初始化 —— Alembic 为 schema 唯一权威。"""

import asyncio


def _run_upgrade() -> None:
    """在独立线程里同步执行 Alembic upgrade head。

    env.py 的在线迁移内部用 ``asyncio.run`` 创建事件循环，而 init_db 在
    FastAPI lifespan（已运行的事件循环）中被调用，直接调用 command.upgrade
    会因 "cannot be called from a running event loop" 崩溃，故放到线程池。
    """
    from pathlib import Path

    from alembic.config import Config

    from alembic import command

    # 复用后端仓库根下的 alembic.ini（含 script_location 与 env.py），
    # 迁移沿用 env.py 的 sqlalchemy.url（来自 settings），不在此覆盖。
    repo_root = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(repo_root / "alembic.ini"))
    command.upgrade(cfg, "head")


async def init_db() -> None:
    """把数据库 schema 升到 Alembic head。

    既负责全新环境的建库（基线迁移建全部表），也负责后续的增量迁移。
    生产与开发复用同一迁移链。
    """
    await asyncio.to_thread(_run_upgrade)
