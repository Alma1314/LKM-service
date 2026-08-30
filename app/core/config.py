import urllib.parse
from typing import ClassVar

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 存在即安全的非生产占位桶：仅当显式认领 dev/local/test 才允许占位密钥。
# 刻意不包含 ""/None —— LKM_ENV 缺失（含显式设为空串）一律按生产 fail-fast，
# 避免"忘了设 LKM_ENV=production"时占位密钥悄悄放行。本地开发默认 env="dev" 不受影响。
_PERMISSIVE_ENVS: set[str] = {"dev", "local", "test"}


class Settings(BaseSettings):
    # 支持项目根目录的 .env 加载（本地开发）；生产无 .env 时走环境变量/默认值
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="LKM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 运行环境：默认 dev（本地），生产显式设 LKM_ENV=production 等非宽松值
    env: str = "dev"

    app_name: str = "LKM-API"
    app_version: str = "0.0.1"
    api_prefix: str = "/api/v1"

    db_driver: str = "sqlite"
    # 生产环境改为：db_driver: str = "postgresql" 或编写.env
    db_path: str = "lkm.db"
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "lkm"
    db_user: str = "postgres"
    db_password: str = ""

    # 连接池（仅 PostgreSQL/asyncpg 生效；SQLite 单文件连接数无益，走 NullPool）
    db_pool_size: int = 10
    db_pool_max_overflow: int = 20
    # 取连接前 ping 探活，剔除坏连接，避免陈旧连接 0 连接时的短暂出错
    db_pool_pre_ping: bool = True

    # JWT 签名密钥 — 所有非测试环境必须覆盖此值
    jwt_secret: str = "change-me-to-a-random-secret-thats-at-least-32-bytes-long"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # 后台 cookie 会话：access cookie 存活分钟（refresh 天数复用 refresh_token_expire_days）
    admin_access_cookie_minutes: int = 15

    # 登录限流安全参数（见 backend_auth_security 记忆）：IP/全局每次数量与窗口秒
    login_ip_max_per_min: int = 20
    login_global_max_per_min: int = 200
    login_window_seconds: int = 60

    # TOTP / 敏感数据加密密钥 — 必须与 jwt_secret 分开设置
    totp_encryption_key: str = "change-me-totp-encryption-key-at-least-32-bytes"

    # 验证码 HMAC 盐值 — 必须与 totp_encryption_key 和 jwt_secret 分开设置
    verification_code_pepper: str = (
        "change-me-verification-code-pepper-at-least-32-bytes"
    )

    # OAuth (GitHub)
    github_client_id: str = ""
    github_client_secret: str = ""
    github_redirect_uri: str = "http://localhost:8000/api/v1/auth/oauth/github/callback"
    frontend_callback: str = "http://localhost:5173/login/success"

    # Passkey (WebAuthn)
    rp_id: str = "localhost"
    rp_name: str = "LKM Service"
    origin: str = "http://localhost:5173"

    blog_repo_dir: str = "blog_repos"
    files_store_dir: str = "files_store"
    max_upload_bytes: int = 100 * 1024 * 1024  # 单文件上传上限 100MB
    redis_url: str = (
        ""  # 空串 = 未启用 Redis；非空走 redis://[user:pass@]host:port[/db]
    )
    rabbit_url: str = (
        ""  # 空串 = 未启用 RabbitMQ；非空走 amqp://[user:pass@]host[:port][/vhost]
    )

    # MinIO/S3 对象事件回调共享令牌：空串 = 未启用（回调端点一律 401）。
    # 生产必须设置固定随机值，供桶通知 webhook 的 Authorization: Bearer 头校验。
    files_notify_token: str = ""

    # schema 初始化策略（开发默认 create_all，免维护增量迁移）：
    #   False（默认）→ init_db 用 Base.metadata.create_all()，只建缺失表、不 ALTER、
    #                  不依赖 Alembic；开发新增表只改 models.py 即可，无需手写迁移文件。
    #             局限：不处理已有表的列变更、不记录 schema 版本（无法增量升级老库）。
    #   True        → 走 Alembic 增量迁移（schema 唯一权威、可回滚、可升级老库）。
    # 建议：生产/有历史数据的环境显式设 LKM_USE_ALEMBIC=true；本地从零开发用默认
    # create_all 免去每张新表写迁移的负担。迁移文件（alembic/versions/*）保留作生产后备。
    use_alembic: bool = False

    # Sentry APM：空串 = 不加载（dev/test 默认关闭，避免拖启动）；配置 DSN 才接入
    sentry_dsn: str = ""
    # Sentry 性能采样率（0~1）；仅 DSN 非空时才生效
    sentry_traces_sample_rate: float = 1.0

    # ---- 存储后端 ----
    storage_backend: str = "local"  # local | s3
    s3_endpoint_url: str = ""  # 留空=云 S3 默认 endpoint；填了=MinIO 本地(容器内连接用)
    s3_public_endpoint_url: str = (
        ""  # 直传/下载预签名 URL 对浏览器暴露的公网地址(填该服务的公网 host)
    )
    s3_region: str = ""
    s3_bucket: str = "lkm"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_prefix: str = "files"  # 桶内 key 前缀

    @model_validator(mode="after")
    def _no_insecure_secrets_outside_dev(self) -> "Settings":
        """生产（非宽松环境）必须提供真实密钥，禁止用 change-me 占位或空串启动。

        宽松环境（dev/local/test/未设）放行，保证本地开发与测试套件不受影响。
        """
        env = (self.env or "").strip().lower()
        if env in _PERMISSIVE_ENVS:
            return self
        placeholders = [
            "change-me",
            "changeme",
            "your-",
            "placeholder",
        ]
        insecure: list[str] = []
        for name, value in (
            ("jwt_secret", self.jwt_secret),
            ("totp_encryption_key", self.totp_encryption_key),
            ("verification_code_pepper", self.verification_code_pepper),
        ):
            v = value or ""
            if not v or any(p in v.lower() for p in placeholders):
                insecure.append(name)
            elif name in ("jwt_secret", "totp_encryption_key") and len(v) < 32:
                insecure.append(f"{name}(too short)")
        if self.jwt_secret == self.totp_encryption_key:
            insecure.append("jwt_secret==totp_encryption_key")
        if insecure:
            raise ValueError(
                "Insecure secrets in production (set LKM_ENV to a non-dev value but secrets "
                f"missing/placeholder): {', '.join(insecure)}"
            )
        return self

    @property
    def is_production(self) -> bool:
        """生产（非宽松环境）才允许 HttpOnly cookie 走 Secure。

        宽松环境（dev/local/test/未设）为 False，cookie 走 http 便于本地联调；
        生产（如 LKM_ENV=production）为 True，要求 https 传输 cookie。
        """
        return (self.env or "").strip().lower() not in _PERMISSIVE_ENVS

    @property
    def database_url(self) -> str:
        if self.db_driver == "postgresql":
            password = urllib.parse.quote_plus(self.db_password)
            return (
                f"postgresql+asyncpg://{self.db_user}:{password}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}"
            )
        return f"sqlite+aiosqlite:///{self.db_path}"


settings = Settings()
