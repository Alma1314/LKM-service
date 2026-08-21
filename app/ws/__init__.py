"""WebSocket 实时推送：跨进程事件广播（broker）与连接管理（manager）。

- ``broker``：worker 进程发布事件到 Redis pub/sub 通道（worker 与 API 共用）。
- ``manager``：API 进程持有 WebSocket 连接，订阅 Redis 通道并扇出给相应用户。
"""
