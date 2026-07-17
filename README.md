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
GET  /api/v1/boards/status         # 板块状态
```

## 运行

```bash
uv sync
uvicorn main:app --reload
```

## 测试

```bash
uv run pytest -v
```
