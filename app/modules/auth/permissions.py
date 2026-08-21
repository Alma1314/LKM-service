"""路由/服务共用的授权判定（模块7 分层权限下沉）。

把「资源属主 或 admin」这类散落在各 router 的内联比较收敛到一处，消除重复并
提供统一语义。双轴模型见 community_permission_model（account_level × role）。
"""

from app.core.err import BizError, CommonErr
from app.modules.auth.deps import CurrentUser


def require_owner_or_admin(
    actor: CurrentUser,
    owner_id: int,
    *,
    detail: str | None = None,
) -> None:
    """断言 actor 是 admin，或本人即资源属主（``owner_id``）；否则抛 FORBIDDEN。

    收敛 columns/forum/files 等「属主或管理员」判定：admin 一律放行，普通成员
    仅限本人资源；其余越权。*detail* 可传资源语义便于错误区分。
    """
    if actor.account_level == "admin" or actor.id == owner_id:
        return
    raise BizError(CommonErr.FORBIDDEN, detail)
