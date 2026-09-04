"""信息流(feed)域错误码：承接 follow 命名空间（关注关系）。"""

from app.core.err import NS_FOLLOW, ErrCode, register


class FollowErr(ErrCode):
    CANNOT_FOLLOW_SELF = NS_FOLLOW.err(1)
    TARGET_NOT_FOUND = NS_FOLLOW.err(2)


register(
    {
        FollowErr.CANNOT_FOLLOW_SELF: (400, "不能关注自己"),
        FollowErr.TARGET_NOT_FOUND: (404, "关注目标不存在"),
    }
)
