"""关注关系请求/响应模型。"""

from pydantic import BaseModel


class FollowToggle(BaseModel):
    """follow/unfollow 操作结果：follower 当前是否正关注该目标。"""

    following: bool


class FollowState(BaseModel):
    """查询某目标对当前用户的关注状态（follow/unfollow 之外的可选展示）。"""

    is_following: bool
