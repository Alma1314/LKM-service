# ---- 构建阶段:用 uv 安装依赖 ----
FROM python:3.13-slim-bookworm AS builder
# 从官方 uv 镜像复制 uv / uvx 二进制(避免依赖 uv 的 python 镜像 tag)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
# 全量安装(含 dev 组):生产 lifespan 跑 alembic upgrade head,必需 alembic
RUN uv sync --frozen --no-install-project

# ---- 运行阶段 ----
FROM python:3.13-slim-bookworm
WORKDIR /app

# git:博客模块 blog_repos 的 git 操作;ca-certificates:HTTPS 拉取
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app"

# 复制应用代码与 alembic 迁移(init_db 在 lifespan 跑迁移)
COPY . .

# 数据持久化目录(由 backend_data 卷挂载到 /data)
ENV LKM_DB_PATH=/data/lkm.db \
    LKM_BLOG_REPO_DIR=/data/blog_repos \
    LKM_FILES_STORE_DIR=/data/files_store

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
