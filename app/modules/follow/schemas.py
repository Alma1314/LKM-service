"""关注关系请求/响应模型。"""

from pydantic import BaseModel


class FollowToggle(BaseModel):
    """follow/unfollow 操作结果：follower 当前是否正关注该目标。"""

    following: bool


class FollowState(BaseModel):
    """查询某目标对当前用户的关注状态（follow/unfollow 之外的可选展示）。"""

    is_following: bool


class FollowUser(BaseModel):
    """「我关注的用户」列表项。"""

    user_id: int
    display_name: str
    avatar: str | None = None


class FollowBoard(BaseModel):
    """「我关注的版块」列表项。"""

    board_id: int
    title: str
