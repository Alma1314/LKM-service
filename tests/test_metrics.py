"""M0.5.1 Prometheus metrics：/metrics 端点与自动 HTTP 埋点。

验收锚定蓝图 M0.5.1：curl /metrics → text/plain 且含 http_requests_total；任意
/api 请求后该计数递增；histogram http_request_duration_seconds_bucket 存在。
全局默认 REGISTRY 跨测试累积，故计数断言一律用「相对增量」（before→after），不做绝对等值。
"""

import re

from tests.conftest import Client

_TOTAL_RE = re.compile(
    r'^http_requests_total\{handler="([^"]*)",method="([^"]*)",status="[^"]*"\} ([\d.]+)$',
    re.MULTILINE,
)


def _series_value(body: str, handler: str, method: str) -> float:
    """取 http_requests_total 某 {handler,method} 的现值；不存在则 0。"""
    for line in body.splitlines():
        m = _TOTAL_RE.match(line)
        if m and m.group(1) == handler and m.group(2) == method:
            return float(m.group(3))
    return 0.0


async def test_metrics_endpoint_is_plain_text_and_exposes_defaults(
    client: Client,
) -> None:
    # 首打一次真实请求，让默认 histogram/计数器产生至少一个样本（零样本时 Prometheus
    # 文本格式只输出 # TYPE 不输出 _bucket 序列，无法断言 bucket）。
    await client.get("/")
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    # 蓝图验收：默认四处指标存在；histogram 带 _bucket 可算 P50/P95/P99
    assert "http_requests_total" in body
    assert "http_request_duration_seconds_bucket" in body
    assert "http_request_size_bytes" in body
    assert "http_response_size_bytes" in body


async def test_auto_instrumentation_increments_on_real_request(
    client: Client,
) -> None:
    # 相对增量：先读 handler="/" 现值，打一次根请求后再读，断言 +1（证明埋点确实埋到真实请求）。
    before = _series_value((await client.get("/metrics")).text, "/", "GET")

    hello = await client.get("/")
    assert hello.status_code == 200

    after = _series_value((await client.get("/metrics")).text, "/", "GET")
    assert after == before + 1
