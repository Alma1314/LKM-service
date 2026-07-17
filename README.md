# LKM Service

理科学迷社区平台的后端服务，当前基于 FastAPI 搭建。

当前代码只保留第一阶段 MVP 所需的基础模块：用户系统、分科板块、内容发布和健康检查。

## 当前架构

```text
.
├── main.py
├── app/
│   ├── main.py
│   ├── api/
│   │   └── router.py
│   ├── core/
│   │   └── config.py
│   ├── db/
│   │   ├── base.py
│   │   ├── init_db.py
│   │   └── session.py
│   └── modules/
│       ├── auth/
│       ├── boards/
│       ├── contents/
│       └── health/
├── pyproject.toml
└── uv.lock
```

## 模块说明

- `main.py`：兼容入口，继续支持 `uvicorn main:app`。
- `app/main.py`：创建 FastAPI 应用并注册总路由。
- `app/core/`：全局配置、认证、安全等公共基础能力。
- `app/db/`：数据库模型基类、数据库连接和会话管理。
- `app/api/router.py`：集中挂载所有业务模块路由。
- `app/modules/auth/`：登录、注册、用户资料、基础角色权限；当前已包含用户 ORM 模型和用户 schema。
- `app/modules/boards/`：分科板块、板块申请、板块运营。
- `app/modules/contents/`：文章、笔记、想法、评论、点赞、收藏、关注。
- `app/modules/health/`：服务健康检查。

## 本地运行

项目声明需要 Python `>=3.13`。

安装依赖后可以运行：

```bash
uvicorn main:app --reload
```

常用检查接口：

```text
GET /
GET /api/v1/health
GET /api/v1/auth/status
GET /api/v1/boards/status
GET /api/v1/contents/status
```

## 开发说明

当前阶段只做第一阶段基础功能，各业务模块的 `/status` 接口用于说明职责和下一步实现方向。后续开发时，建议按模块逐步补充：

1. 数据库模型
2. 请求和响应 schema
3. service 业务逻辑
4. API 路由
5. 认证、权限和数据校验

后续阶段的文件库、积分、专栏、求助、项目、竞赛、匿名信和资助模块暂不保留空框架，等进入对应阶段时再新增。

## 当前进度

- 已搭建 FastAPI 分层结构。
- 已保留第一阶段模块：`auth`、`boards`、`contents`、`health`。
- 已增加 SQLAlchemy 数据库基础层和开发期建表辅助函数。
- 已定义用户表模型和用户创建/读取 schema。

下一步建议实现用户注册接口，包括密码哈希、用户名/邮箱唯一性检查和写入数据库。
