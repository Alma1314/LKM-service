"""数据库初始化 —— Alembic 为 schema 唯一权威。"""


def init_db() -> None:
    """把数据库 schema 升到 Alembic head。

    既负责全新环境的建库（基线迁移建全部表），也负责后续的增量迁移。
    生产与开发复用同一迁移链。
    """
    from pathlib import Path

    from alembic.config import Config

    from alembic import command

    # 复用后端仓库根下的 alembic.ini（含 script_location 与 env.py），
    # 迁移沿用 env.py 的 sqlalchemy.url（来自 settings），不在此覆盖。
    repo_root = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(repo_root / "alembic.ini"))
    command.upgrade(cfg, "head")
