"""验证码 / 魔法链接发送（worker 侧执行）。
channels/deps 只在函数内延迟 import，避免 worker 冷启动时经 send→deps→
providers/security→db.models/session 拉整棵 auth 树，缩短 worker 启动路径。
"""

from typing import Any


async def send_code(ctx: Any, channel_key: str, contact: str, code: str) -> None:
    """发送验证码。*ctx* 为 ARQ 注入的 TaskContext(未用)。失败抛异常触发重试。"""
    from app.modules.auth import channels as _channels

    await _channels.CHANNELS[channel_key].send_code(contact, code)


async def send_magic_link(ctx: Any, email: str, link: str) -> None:
    """发送魔法链接。*ctx* 为 ARQ 注入的 TaskContext(未用)。"""
    from app.modules.auth import deps as _deps

    await _deps.get_email_provider().send_magic_link(email, link)
