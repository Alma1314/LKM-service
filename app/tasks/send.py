"""ARQ 任务：验证码 / 魔法链接发送（worker 侧执行）。"""

from typing import Any

from app.modules.auth import channels as _channels
from app.modules.auth import deps as _deps


async def send_code(ctx: Any, channel_key: str, contact: str, code: str) -> None:
    """发送验证码。*ctx* 为 ARQ 注入的 TaskContext(未用)。失败抛异常触发重试。"""
    await _channels.CHANNELS[channel_key].send_code(contact, code)


async def send_magic_link(ctx: Any, email: str, link: str) -> None:
    """发送魔法链接。*ctx* 为 ARQ 注入的 TaskContext(未用)。"""
    await _deps.get_email_provider().send_magic_link(email, link)
