from pydantic import model_validator
from pydantic_settings import BaseSettings

# 存在即安全的非生产占位桶：仅当 env 属于这二者时允许占位密钥，其余一律 fail-fast
_PERMISSIVE_ENVS = {"", None, "dev", "local", "test"}


class Settings(BaseSettings):
    # 支持项目根目录的 .env 加载（本地开发）；生产无 .env 时走环境变量/默认值
    model_config = {"env_prefix": "LKM_", "env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

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

    # JWT 签名密钥 — 所有非测试环境必须覆盖此值
    jwt_secret: str = "change-me-to-a-random-secret-thats-at-least-32-bytes-long"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # TOTP / 敏感数据加密密钥 — 必须与 jwt_secret 分开设置
    totp_encryption_key: str = "change-me-totp-encryption-key-at-least-32-bytes"

    # 验证码 HMAC 盐值 — 必须与 totp_encryption_key 和 jwt_secret 分开设置
    verification_code_pepper: str = "change-me-verification-code-pepper-at-least-32-bytes"

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
            return (
                f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}"
            )
        return f"sqlite:///{self.db_path}"


settings = Settings()