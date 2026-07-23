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
│       ├── columns/           # 专栏申请、专栏、专栏文章
│       └── health/
├── alembic/                   # Alembic 环境配置，当前需补充 versions 迁移文件
├── tests/
├── pyproject.toml
└── uv.lock
```

## 接口概览

基础接口：

```text
GET  /                              # 根路径探活，不走 ApiResp
GET  /api/v1/health                 # 健康检查
GET  /api/v1/boards/status          # 分科板块模块状态
```

认证与用户资料：

```text
POST /api/v1/auth/reg               # 兼容旧注册入口，返回认证信息
POST /api/v1/auth/login             # 兼容旧登录入口，需要 2FA 时会提示使用新登录流
GET  /api/v1/auth/me                # 获取当前 JWT 用户
GET  /api/v1/auth/{user_id}         # 获取用户展示信息
PUT  /api/v1/auth/{user_id}/profile # 更新自己的展示信息

POST /api/v1/auth/reg/local         # 创建本地账号
POST /api/v1/auth/reg/normal        # 发起普通账号注册，发送验证码
POST /api/v1/auth/reg/normal/verify # 完成普通账号注册
POST /api/v1/auth/reg/phone         # 发起手机号注册
POST /api/v1/auth/reg/phone/verify  # 完成手机号注册
POST /api/v1/auth/reg/email         # 发起邮箱注册
POST /api/v1/auth/reg/email/verify  # 完成邮箱注册

POST /api/v1/auth/login/password           # 密码登录，支持 2FA 流程
POST /api/v1/auth/login/code/request       # 请求邮箱/手机号登录验证码
POST /api/v1/auth/login/code               # 验证码登录
POST /api/v1/auth/login/magic-link/request # 请求登录魔法链接
GET  /api/v1/auth/login/magic-link/verify  # 验证登录魔法链接
POST /api/v1/auth/refresh                  # 刷新 access token
POST /api/v1/auth/logout                   # 吊销当前用户 refresh token
```

2FA / TOTP：

```text
POST   /api/v1/auth/2fa/setup/begin         # 已登录用户开始设置 TOTP
POST   /api/v1/auth/2fa/setup/temp          # 使用临时 token 开始强制 TOTP 设置
POST   /api/v1/auth/2fa/setup/complete      # 完成 TOTP 设置
POST   /api/v1/auth/2fa/setup/complete/temp # 完成强制 TOTP 设置并返回 token
POST   /api/v1/auth/2fa/setup/confirm       # 确认已保存恢复码
POST   /api/v1/auth/2fa/verify              # 登录时验证 TOTP 或恢复码
DELETE /api/v1/auth/2fa                     # 禁用 TOTP
```

OAuth / Passkey / 设置 / 恢复：

```text
GET  /api/v1/auth/oauth/github/login          # 重定向到 GitHub OAuth 登录
GET  /api/v1/auth/oauth/github/callback       # GitHub OAuth 登录回调
POST /api/v1/auth/oauth/github/login/redirect # 获取用于绑定 GitHub 的授权 URL
GET  /api/v1/auth/oauth/github/bind-callback  # GitHub 绑定回调

POST   /api/v1/auth/passkey/register/begin    # 开始注册 Passkey
POST   /api/v1/auth/passkey/register/complete # 完成注册 Passkey
POST   /api/v1/auth/passkey/login/begin       # 开始 Passkey 登录
POST   /api/v1/auth/passkey/login/complete    # 完成 Passkey 登录
GET    /api/v1/auth/passkey/credentials       # 当前用户 Passkey 凭据列表
DELETE /api/v1/auth/passkey/{cred_id}         # 删除 Passkey 凭据

POST /api/v1/auth/settings/bind-email/request # 请求绑定邮箱验证码
POST /api/v1/auth/settings/bind-email/verify  # 验证并绑定邮箱
POST /api/v1/auth/settings/bind-phone/request # 请求绑定手机号验证码
POST /api/v1/auth/settings/bind-phone/verify  # 验证并绑定手机号

POST /api/v1/auth/recover/check                # 查询账号可用恢复方式
POST /api/v1/auth/recover/phone                # 请求手机号恢复验证码
POST /api/v1/auth/recover/phone/verify         # 验证手机号恢复码
POST /api/v1/auth/recover/email                # 请求邮箱恢复验证码
POST /api/v1/auth/recover/email/verify         # 验证邮箱恢复码
POST /api/v1/auth/recover/magic-link           # 请求恢复魔法链接
POST /api/v1/auth/recover/magic-link/verify    # 验证恢复魔法链接
POST /api/v1/auth/recover/verify-totp          # 用户恢复流程验证 2FA
POST /api/v1/auth/recover/complete             # 用户恢复流程设置新密码
POST /api/v1/auth/recover/admin/begin          # 管理员恢复流程开始
POST /api/v1/auth/recover/admin/verify-contact # 管理员恢复流程验证联系方式
POST /api/v1/auth/recover/admin/verify-totp    # 管理员恢复流程验证 2FA
POST /api/v1/auth/recover/admin/complete       # 管理员恢复流程设置新密码
```

专栏接口：

```text
GET  /api/v1/columns/status                         # 专栏模块状态
GET  /api/v1/columns/plan                           # 专栏数据表和开发计划
POST /api/v1/columns/applications                   # 提交专栏申请，需要 X-User-Id
GET  /api/v1/columns/applications                   # 专栏申请列表
GET  /api/v1/columns/applications/{application_id}  # 专栏申请详情
POST /api/v1/columns/applications/{application_id}/review # 审核专栏申请，需要 X-User-Id
GET  /api/v1/columns                                # 专栏列表
GET  /api/v1/columns/{column_id}                    # 专栏详情
POST /api/v1/columns/{column_id}/posts              # 发布专栏文章，需要 X-User-Id
GET  /api/v1/columns/{column_id}/posts              # 专栏文章列表
GET  /api/v1/columns/{column_id}/posts/{post_id}    # 专栏文章详情
```

## 身份请求头

当前项目同时存在两套身份入口：

- 认证系统使用 `Authorization: Bearer <access_token>`，由 `get_current_user` 解析。
- 专栏第一阶段仍使用 `X-User-Id` 做 header/body 一致性校验。

后续建议逐步把专栏写接口也迁移到 JWT 当前用户体系

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
