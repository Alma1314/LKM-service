"""时间线响应模型。"""

from datetime import datetime

from pydantic import BaseModel


class FeedItem(BaseModel):
    """统一 feed 条目（跨源归一后）。"""

    item_type: str  # forum | article | column | qa | project
    id: int
    author_id: int | None  # Article 无作者外键 → None
    author_name: str
    title: str
    content_preview: str
    created_at: datetime
    sort_score: float
    board_id: int | None = None
    url: str


class FeedResponse(BaseModel):
    """时间线响应：条目 + 下一页游标。

    ``next_cursor`` 为 None 表示已到末尾；游标为 Base64 编码的
    ``"{iso_time}|{id}"``，按 (created_at, id) 下滤。
    """

    items: list[FeedItem]
    next_cursor: str | None
