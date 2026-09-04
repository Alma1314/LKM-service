"""可观测基座 · Prometheus metrics（M0.5.1）。

与 sentry(apm.py) 平行的本体可观测接入：给 FastAPI 加自动 HTTP 埋点并暴露 /metrics
抓取端点。语义同 Sentry：

- 默认开启（本地无副作用收集器，成本极低）；`LKM_METRICS_ENABLED=false` 可整体关闭；
  关闭/初始化失败一律 fail-open（仅记日志，不阻塞应用启动）。
- 幂等：仅在首次装配挂载，重复调用不重复注册（prometheus_client 用全局默认 REGISTRY，
  同名 metric 重复注册会抛 ValueError）。
"""

import logging

from fastapi import FastAPI

from app.core.config import settings

logger = logging.getLogger(__name__)


def setup_metrics(app: FastAPI) -> None:
    """按 settings 装配 /metrics + 自动 HTTP 埋点；关闭或缺依赖均 fail-open（幂等）。"""
    if not settings.metrics_enabled:
        logger.info("Prometheus metrics 已关闭（LKM_METRICS_ENABLED=false）")
        return
    try:
        # 延迟导入：prometheus 依赖缺失时静默降级，防止把监控变启动硬依赖
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator().instrument(app).expose(
            app,
            endpoint=settings.metrics_endpoint,
            include_in_schema=False,
            tags=["monitoring"],
        )
        logger.info("Prometheus metrics 已挂载 %s", settings.metrics_endpoint)
    except Exception:
        logger.exception("Prometheus metrics 挂载失败，降级为不加载（fail-open）")
