"""API 进程侧：持有 WebSocket 连接，订阅 Redis 通道并扇出给对应 uploader。

worker 进程只 ``publish_upload_bound``（见 broker.py），不持有连接；连接唯一存在于
API 进程（本模块）。Redis 订阅用常驻后台 task（幂等懒启动，首次 WS 连接时拉起），
集中 ``psubscribe ws:upload:*`` 再按通道尾部的 user_id 扇出 —— 避免每个连接一条
sub 连接。
"""

import asyncio
from collections import defaultdict
from contextlib import suppress
from typing import Any, Protocol

from app.core.redis import get_redis
from app.ws.broker import _UPLOAD_CHANNEL_PREFIX


class Dispatcheable(Protocol):
    """Manager 只依赖的推送接口：任意能 ``await send_text(str)`` 的连接均可注册。"""

    async def send_text(self, data: str) -> None: ...


class ConnectionManager:
    """以 user_id 为键的活动连接集合 + Redis 订阅驱动的扇出。"""

    def __init__(self) -> None:
        self._connections: dict[int, set[Dispatcheable]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._sub_task: asyncio.Task[Any] | None = None
        self._start_lock = asyncio.Lock()

    async def register(self, user_id: int, ws: Dispatcheable) -> None:
        async with self._lock:
            self._connections[user_id].add(ws)

    async def unregister(self, user_id: int, ws: Dispatcheable) -> None:
        async with self._lock:
            s = self._connections.get(user_id)
            if s:
                s.discard(ws)
                if not s:
                    self._connections.pop(user_id, None)

    async def dispatch(self, user_id: int, message: str) -> None:
        """向某用户的所有连接推送同一文本消息。失效连接尽力移除，不阻塞整体。"""
        async with self._lock:
            targets: list[Dispatcheable] = list(self._connections.get(user_id, ()))
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                async with self._lock:
                    self._connections.get(user_id, set()).discard(ws)

    # ---- Redis 订阅驱动（生命周期）----

    async def ensure_subscription(self) -> None:
        """幂等启动全局订阅 task；已运行/启动中则跳过。"""
        if self._sub_task is not None and not self._sub_task.done():
            return
        async with self._start_lock:
            if self._sub_task is not None and not self._sub_task.done():
                return
            self._sub_task = asyncio.create_task(self._sub_loop())

    async def _sub_loop(self) -> None:
        """常驻：psubscribe ws:upload:* → 解析 user_id → dispatch。

        Redis 未就绪就退避重试；订阅连接异常同样退避重连。取消即退出。
        """
        while True:
            redis = await get_redis()
            if redis is None:
                await asyncio.sleep(1)
                continue
            pubsub = redis.pubsub()
            try:
                await pubsub.psubscribe(f"{_UPLOAD_CHANNEL_PREFIX}*")
                while True:
                    msg: dict[str, Any] | None = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=1.0
                    )
                    if msg is None:
                        continue
                    if msg.get("type") != "pmessage":
                        continue
                    channel = msg.get("channel")
                    data = msg.get("data")
                    if isinstance(data, bytes):
                        data = data.decode()
                    if not isinstance(channel, str) or not isinstance(data, str):
                        continue
                    try:
                        user_id = int(channel.rsplit(":", 1)[1])
                    except (ValueError, IndexError):
                        continue
                    await self.dispatch(user_id, data)
            except asyncio.CancelledError:
                raise
            except Exception:
                # 订阅链路异常：关连接后退避重连，保持常驻
                with suppress(Exception):
                    await pubsub.aclose()
                await asyncio.sleep(1)

    async def close(self) -> None:
        """收尾：取消订阅 task，避免泄漏 Redis 连通。幂等。"""
        task, self._sub_task = self._sub_task, None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


# 全局唯一管理器实例（进程内共享）
manager = ConnectionManager()
