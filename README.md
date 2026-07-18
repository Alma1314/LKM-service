# LKM Service

理科迷社区后端服务，FastAPI + SQLite。

## 结构

```
.
├── main.py                  # 兼容入口: uvicorn main:app
├── app/
│   ├── main.py              # create_app(), 异常处理器
│   ├── api/router.py        # 挂载各模块路由
│   ├── core/
│   │   ├── config.py        # Settings
│   │   └── err.py           # ErrCode / BizError / ERRTABLE / map_err
│   ├── db/
│   │   ├── init_db.py       # CREATE TABLE
│   │   └── session.py       # getdb() 上下文管理器
│   └── modules/
│       ├── common.py        # ApiResp, ModuleStatus
│       ├── auth/
│       │   ├── router.py    # POST /reg  /login
│       │   ├── schemas.py   # UserRegInfo, UserLoginInfo, Password
│       │   ├── security.py  # hashpwd, verifypwd
│       │   └── service.py   # register, login 业务逻辑
│       ├── boards/
│       ├── columns/         # 专栏申请、专栏、专栏文章框架
│       └── health/
├── tests/test_auth.py
├── pyproject.toml
└── uv.lock
```

## 接口

```
GET  /                             # 健康探活
GET  /api/v1/health                # 健康检查
POST /api/v1/auth/reg              # 注册
POST /api/v1/auth/login            # 登录
GET  /api/v1/auth/{user_id}        # 用户展示信息
PUT  /api/v1/auth/{user_id}/profile # 更新展示信息
GET  /api/v1/boards/status         # 板块状态
GET  /api/v1/columns/status        # 专栏模块状态
GET  /api/v1/columns/plan          # 专栏数据表和开发计划
POST /api/v1/columns/applications # 提交专栏申请
GET  /api/v1/columns/applications # 专栏申请列表
GET  /api/v1/columns/applications/{application_id} # 专栏申请详情
POST /api/v1/columns/applications/{application_id}/review # 审核专栏申请
GET  /api/v1/columns              # 专栏列表
GET  /api/v1/columns/{column_id}  # 专栏详情
POST /api/v1/columns/{column_id}/posts # 发布专栏文章
GET  /api/v1/columns/{column_id}/posts # 专栏文章列表
GET  /api/v1/columns/{column_id}/posts/{post_id} # 专栏文章详情
```

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

模块状态接口（如 `/api/v1/boards/status`、`/api/v1/columns/status`）直接返回 `ModuleStatus`，包含 `module`、`status`、`responsibility`、`next_steps`。

根路径 `/` 不走统一响应结构，仅返回 `{"message": "OK"}`。

## 错误处理

`ERRTABLE` 集中映射错误码 → HTTP 状态 + 默认消息。`@respond` 装饰器动态包装返回值：

- 返回 `dict` → 自动包成 `OK` 响应
- 返回 `(ErrCode, str)` → 按该错误码包，str 作为 detail
- 返回 `(ErrCode, dict)` → 按该错误码包，dict 作为 data

## 技术选型

- **`users` / `profiles` 分表**：注册信息和展示信息独立存储，注册时自动创建空 profile。
- **`columns` 最小业务闭环**：当前已支持专栏申请、审核通过后自动创建专栏、专栏列表/详情、专栏文章发布/列表/详情；暂不接角色权限。

## 运行

```bash
uv sync
uvicorn main:app --reload
```

## 测试

```bash
uv run pytest -v
```
