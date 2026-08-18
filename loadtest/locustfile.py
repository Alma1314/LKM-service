"""LKM 后端热路径负载压测（模块1 压测基座 · locust）。

覆盖公开只读热点：articles/columns/forum/blog 列表、categories、members、health，
以及一组低频 auth 密码登录（受 Redis 限流，用于观测限流下行为）。

运行（生产/本地起多 worker 后）：
    uv run locust -f loadtest/locustfile.py --host http://localhost:8000 \
        --users 50 --spawn-rate 5 --run-time 1m --headless -u 50 -r 5 -t 1m
快速 smoke（本地单机）：
    uv run locust -f loadtest/locustfile.py --host http://localhost:8000 \
        --users 10 --spawn-rate 5 --run-time 20s --headless -u 10 -r 5 -t 20s
"""

from locust import HttpUser, between, task

# members 公开静态数据组，任选其一保证 200
_MEMBER_TYPE = "generalMembers"
# auth 登录探测：密码登录走 Redis 限流，负载下多数会被限流拒(ACCOUNT_LOCKED)，属预期
_LOGIN_USER = "bench_user"
_LOGIN_PASSWORD = "BenchPass!123"


class LKMReadUser(HttpUser):
    """公开只读热路径：加权打列表/详情 / 分类 / 组成员 / 健康。"""

    wait_time = between(0.1, 0.3)

    @task(6)
    def list_articles(self) -> None:
        self.client.get("/api/v1/articles")

    @task(4)
    def list_articles_categories(self) -> None:
        self.client.get("/api/v1/articles/categories")

    @task(4)
    def list_columns(self) -> None:
        self.client.get("/api/v1/columns")

    @task(4)
    def list_forum_posts(self) -> None:
        self.client.get("/api/v1/forum/posts")

    @task(4)
    def list_blog_series(self) -> None:
        self.client.get("/api/v1/blog/series")

    @task(3)
    def members_general(self) -> None:
        self.client.get(f"/api/v1/members?type={_MEMBER_TYPE}")

    @task(1)
    def health(self) -> None:
        # 健康检查→聚合 DB+Redis，压测下可观测 DB/Redis 探测路径
        self.client.get("/api/v1/health")


class LKMAuthUser(HttpUser):
    """低频 auth 登录：命中 Redis 限流为预期，用于观测登录路径与限流失效行为。"""

    wait_time = between(1, 3)

    @task
    def login_password(self) -> None:
        # 400/401/423(限流) 均为预期分支；只对网络/5xx 计失败
        with self.client.post(
            "/api/v1/auth/login/password",
            json={"username": _LOGIN_USER, "password": _LOGIN_PASSWORD},
            catch_response=True,
        ) as resp:
            if resp.status_code >= 500:
                resp.failure(f"5xx: {resp.status_code}")
            elif resp.status_code in (200, 400, 401, 403, 423):
                resp.success()
            else:
                resp.success()
