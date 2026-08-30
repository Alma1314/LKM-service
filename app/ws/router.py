"""WebSocket 实时端点：用户建立连接，订阅其上传登记完成事件。

浏览器 ``WebSocket`` 无法携带自定义请求头，鉴权改用握手 query 参数 ``token``
（短时效 access token）。校验复用 ``_resolve_current_user`` 的完整语义
（用户存在/锁定/token_version/改密），会话自建自关（同 worker 模式）。

连接建立后由 ``manager`` 统一登记与 Redis 订阅驱动。端点本身只维持连接、
感知对端断开，不要求客户端回业务消息。
"""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db.session import new_session
from app.modules.auth.deps import _resolve_current_user
from app.ws.manager import manager

router = APIRouter(prefix="/ws", tags=["ws"])

# 校验失败的私有 close code（沿用业界常见 4xxx 保留段）
_UNAUTHORIZED_CLOSE = 4401

# 心跳间隔：超过此窗口未收到任何对端消息，则发一条 ping 探活；
# 若对端已静默断线（NAT 过期/断网），send 会抛错从而清理僵尸连接，避免长期占内存。
_HEARTBEAT_S = 30.0


async def _authorize(token: str) -> int | None:
    """校验 access token，返回 user_id；缺失/无效返回 None。"""
    if not token:
        return None
    db = await new_session()
    try:
        cur = await _resolve_current_user(token, db)
    except Exception:
        return None
    finally:
        await db.close()
    return cur.id


@router.websocket("/events")
async def ws_events(websocket: WebSocket) -> None:
    """实时连接：`?token=<access>` 鉴权成功则推送上传登记事件。"""
    token = websocket.query_params.get("token", "")
    user_id = await _authorize(token)
    if user_id is None:
        await websocket.close(code=_UNAUTHORIZED_CLOSE)
        return

    await websocket.accept()
    await manager.register(user_id, websocket)
    await manager.ensure_subscription()
    try:
        # 只推送；循环接收以维持连接并感知对端断开（收到文本即忽略）。
        # 心跳：Starlette 无内置服务端 receive 超时，客户端静默断线时 receive_text()
        # 会无限挂起占住连接。这里用 wait_for 加窗，超时即发 ping 探活——对端已死时
        # send 抛错进入外层 except 清理，僵尸连接不再长期占内存。
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=_HEARTBEAT_S)
            except TimeoutError:
                # 对端已死时 send 抛错 → break 触发 finally 清理
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        await manager.unregister(user_id, websocket)
