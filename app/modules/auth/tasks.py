"""auth 模块队列任务：验证码 / 魔法链接发送（worker 侧执行）。

channels/deps 只在函数内延迟 import，避免 worker 冷启动时经 send→deps→
providers/security→db 拉整棵 auth 树，缩短 worker 启动路径。

任务经 ``register_task`` 注册到 send 队列（§6.2），worker 启动时导入本模块
即触发注册，worker.py 不再手写 handler 表。
"""

from app.core.task_registry import register_queue, register_task

QUEUE = "lkm.send"  # 本模块任务归属队列（send worker 进程消费）
ROUTING_KEYS = ["event.send_code", "event.send_magic_link"]

register_queue(QUEUE, ROUTING_KEYS)


async def send_code(channel_key: str, contact: str, code: str) -> None:
    """发送验证码。失败抛异常触发重试。"""
    from app.modules.auth import channels as _channels

    await _channels.CHANNELS[channel_key].send_code(contact, code)


async def send_magic_link(email: str, link: str) -> None:
    """发送魔法链接。失败抛异常触发重试。"""
    from app.modules.auth import deps as _deps

    await _deps.get_email_provider().send_magic_link(email, link)


register_task(QUEUE, "send_code", send_code)
register_task(QUEUE, "send_magic_link", send_magic_link)
