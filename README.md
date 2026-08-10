# LKM Service

理科迷社区后端服务，基于 FastAPI、SQLAlchemy 和 SQLite/PostgreSQL。

## 当前能力

- 用户系统：本地账号、普通账号、邮箱/手机号注册、密码登录、验证码登录、魔法链接登录。
- Token 体系：JWT access token、refresh token、登出时吊销 refresh token。
- 账号安全：账号等级、锁定状态、登录失败计数、登录限流。
- 2FA：TOTP 设置、验证、恢复码确认、禁用。
- OAuth：GitHub 登录与账号绑定。
- Passkey：WebAuthn 注册、登录、凭据列表和删除。
- 账号恢复：用户恢复、管理员恢复、邮箱/手机号/魔法链接恢复流程。
- 专栏系统：专栏申请、审核、自动创建专栏、专栏文章发布与查询。
- 博客系统：Git 仓库托管博客系列、文章文件读取、星标收藏、评论。
- 数据库：开发环境自动建表；生产环境预期使用 Alembic 管理迁移。

## 项目结构

```text
.
├── main.py                    # 兼容入口：uvicorn main:app
├── app/
│   ├── main.py                # create_app(), lifespan, 异常处理器, 启动安全检查
│   ├── api/router.py          # 挂载 health/auth/boards/columns 等模块路由
│   ├── core/
│   │   ├── config.py          # Settings，读取 LKM_ 前缀环境变量
│   │   ├── err.py             # ErrCode / BizError / ERRTABLE / respond
│   │   └── rate_limit.py      # 内存滑动窗口限流器
│   ├── db/
│   │   ├── models.py          # users/profiles/columns 等主模型
│   │   ├── init_db.py         # 开发环境自动建表
│   │   └── session.py         # SQLAlchemy engine/session 依赖
│   └── modules/
│       ├── common.py          # ApiResp, ListData, ModuleStatus
│       ├── auth/
│       │   ├── router.py          # 注册、登录、token、profile、me
│       │   ├── router_2fa.py      # TOTP / recovery code
│       │   ├── router_oauth.py    # GitHub OAuth
│       │   ├── router_passkey.py  # Passkey / WebAuthn
│       │   ├── router_recovery.py # 账号恢复
│       │   ├── router_settings.py # 邮箱/手机号绑定
│       │   ├── models.py          # refresh token、验证码、OAuth、TOTP、Passkey 等认证表
│       │   ├── schemas.py         # auth 请求/响应模型
│       │   ├── security.py        # 密码哈希、JWT、临时 token 等安全工具
│       │   └── service_*.py       # auth 业务逻辑
│       ├── boards/
│       ├── blog/                # 博客系列、Git 文件读取、星标、评论
│       ├── columns/           # 专栏申请、专栏、专栏文章
│       └── health/
├── alembic/                   # Alembic 环境配置，当前需补充 versions 迁移文件
├── tests/
├── pyproject.toml
└── uv.lock
```

## 接口概览

基础入口：

```text
GET  /                              # 根路径探活，不走 ApiResp
GET  /api/v1/health                 # 健康检查
GET  /api/v1/boards/status          # 分科板块模块状态
```

完整接口文档见 [OpenAPI 规范](docs/openapi/openapi.yaml)。以下为接口分组摘要：

| 模块 | 前缀 | 说明 |
|------|------|------|
| Health | `/health` | 健康检查 |
| Auth | `/auth` | 注册（local/normal/phone/email）、登录（password/code/magic-link）、Token 刷新与吊销、用户资料 |
| Auth 2FA | `/auth/2fa` | TOTP 设置、验证、禁用、恢复码确认 |
| Auth OAuth | `/auth/oauth` | GitHub 登录与账号绑定 |
| Auth Passkey | `/auth/passkey` | WebAuthn 注册、登录、凭据管理 |
| Auth Settings | `/auth/settings` | 邮箱/手机号绑定 |
| Auth Recovery | `/auth/recover` | 用户自助恢复 + 管理员恢复流程 |
| Columns | `/columns` | 专栏申请、审核、文章发布 |
| Forum | `/forum` | 社区帖子分页浏览、发布、点赞、删除，评论（含回复与楼层号） |
| Files | `/files` | 文件库上传（pending 待审核）、列表筛选排序、详情浏览计数、下载计数 |
| Blog | `/blog` | 博客系列 CRUD、Git 文件读取、星标、评论 |
| Blog Git | `/blog/git` | Git HTTP 后端（仓库读写，Basic Auth 认证） |
| Boards | `/boards` | 分科板块（规划中） |

## 身份认证

所有写操作使用 `Authorization: Bearer <access_token>`（JWT），由 `get_current_user` 解析。

Git HTTP 端点（`/blog/git`）使用 HTTP Basic Auth（用户名+密码）。

## 响应结构

普通业务接口统一返回 `ApiResp`：

```json
{
  "code": 0,
  "msg": "OK",
  "data": {}
}
```

错误响应也使用同一结构，`code` 为业务错误码，`msg` 为错误说明，HTTP 状态码由 `ERRTABLE` 映射。

模块状态接口，如 `/api/v1/boards/status`、`/api/v1/columns/status`，直接返回 `ModuleStatus`，包含：

```json
{
  "module": "columns",
  "status": "implemented_minimal",
  "responsibility": "...",
  "next_steps": []
}
```

根路径 `/` 不走统一响应结构，仅返回：

```json
{"message": "OK"}
```

## 数据库与迁移

开发环境启动时会执行：

```python
Base.metadata.create_all(bind=engine)
```

因此 SQLite 本地开发可以自动建表。

生产环境预期使用 Alembic 管理迁移。当前仓库已有 `alembic/env.py` 和模板文件，但没有看到 `alembic/versions` 迁移版本文件；如果要在已有数据库上升级，需要补充正式 migration。

## 运行

```bash
uv sync
uvicorn main:app --reload
```

## 测试

```bash
uv run pytest -v
```

如果安装了项目开发依赖，可以继续运行静态检查：

```bash
uv run pyright
```
