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
```

## 错误处理

`ERRTABLE` 集中映射错误码 → HTTP 状态 + 默认消息。`@respond` 装饰器动态包装返回值：

- 返回 `dict` → 自动包成 `OK` 响应
- 返回 `(ErrCode, str)` → 按该错误码包，str 作为 detail
- 返回 `(ErrCode, dict)` → 按该错误码包，dict 作为 data

## 技术选型

- **`users` / `profiles` 分表**：注册信息和展示信息独立存储，注册时自动创建空 profile。

## 运行

```bash
uv sync
uvicorn main:app --reload
```

## 测试

```bash
uv run pytest -v
```
