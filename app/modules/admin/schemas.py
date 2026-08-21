import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from app.modules.auth.schemas import Password


class AdminLoginReq(BaseModel):
    """后台登录请求体（与前台同构，密码走同一套 Password 校验/哈希）。"""

    username: str = Field(..., min_length=1, max_length=100)
    password: Password = Field(...)


class AdminVerify2FARequest(BaseModel):
    """后台危险操作 step-up：提交的 6 位 TOTP 码。"""

    code: str = Field(..., min_length=6, max_length=6)


class AdminUserOut(BaseModel):
    """后台返回的管理员自身信息。仅暴露登录所需的少量字段，不含敏感 PII。"""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    username: str
    account_level: str
    created_at: datetime.datetime


class AdminUserListItem(BaseModel):
    """后台用户列表项。默认不含邮箱/手机等 PII；include_pii=True 时才带。"""

    id: int
    username: str
    account_level: str
    is_locked: bool
    created_at: datetime.datetime
    # PII（默认隐藏）
    email: str | None = None
    phone: str | None = None


class AdminStats(BaseModel):
    """后台仪表盘聚合统计。"""

    user_count: int
    post_count: int
    file_count: int
    file_pending_count: int


class AdminReportListItem(BaseModel):
    """后台举报列表项。type: post/comment/file；status: pending/resolved/dismissed。"""

    id: int
    type: str
    target_id: str
    target_title: str
    reporter_name: str
    reason: str
    status: str
    created_at: datetime.datetime
    handled_at: datetime.datetime | None = None
