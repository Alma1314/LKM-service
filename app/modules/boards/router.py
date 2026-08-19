from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import (
    bump_collection_version,
    cache_invalidate,
    cached_read,
    collection_version,
    make_key,
)
from app.core.err import respond
from app.db.session import get_read_session, get_session
from app.modules.admin.deps import require_admin
from app.modules.auth.deps import CurrentUser, RequireLevel, get_current_user
from app.modules.boards.errors import BoardErr  # noqa: F401  (副作用注册已由 main 统一)
from app.modules.boards.schemas import (
    BanRequest,
    BoardApplicationCreate,
    BoardApplicationOut,
    BoardCreate,
    BoardOut,
    BoardUpdate,
    ReviewBoardApplicationRequest,
)
from app.modules.boards.service import (
    ban_user,
    create_board_ex,
    get_board_ex,
    list_boards,
    review_application,
    submit_application,
    unban_user,
    update_board_ex,
)
from app.modules.common import ApiResp, ListData, ModuleStatus

CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
AdminDep = Annotated[CurrentUser, require_admin]


def _status() -> ModuleStatus:
    return ModuleStatus(
        module="boards",
        status="implemented",
        responsibility="主题板块：帖子/专栏按板块组织，板块申请与负责人流，禁言与发言准入。",
        next_steps=[
            "前端板块页接线（forum/column 改用 boardId）",
            "积分/通知联动（阶段4）",
            "竞赛/QA/项目挂板块（后端未建）",
        ],
    )


router = APIRouter(prefix="/boards", tags=["boards"])


@router.get("/status", response_model=ModuleStatus)
async def boards_status() -> ModuleStatus:
    return _status()


@router.get("", response_model=ApiResp[ListData[BoardOut]])
@respond
async def board_list(db: AsyncSession = Depends(get_read_session)) -> dict[str, object]:
    async def load() -> dict[str, object]:
        return {"items": await list_boards(db)}

    ver = await collection_version("boards")
    return await cached_read(make_key("boards:list", ver), 60, load)


@router.get("/{board_id}", response_model=ApiResp[BoardOut])
@respond
async def board_detail(
    board_id: int, db: AsyncSession = Depends(get_read_session)
) -> BoardOut:
    async def load() -> BoardOut:
        return BoardOut.model_validate(await get_board_ex(db, board_id))

    return await cached_read(make_key("boards:item", board_id), 300, load)


# 管理端
@router.post("", response_model=ApiResp[BoardOut])
@respond
async def admin_create_board(
    info: BoardCreate,
    _cur: CurrentUser = RequireLevel("admin"),
    db: AsyncSession = Depends(get_session),
) -> BoardOut:
    board = await create_board_ex(db, info, owner_id=None)
    await bump_collection_version("boards")
    return board


@router.post("/applications", response_model=ApiResp[BoardApplicationOut])
@respond
async def submit_app(
    info: BoardApplicationCreate,
    cur: CurrentUser = RequireLevel("normal"),
    db: AsyncSession = Depends(get_session),
) -> BoardApplicationOut:
    return await submit_application(db, cur.id, info)


@router.post(
    "/applications/{app_id}/review", response_model=ApiResp[BoardApplicationOut]
)
@respond
async def review_app(
    app_id: int,
    body: ReviewBoardApplicationRequest,
    _cur: AdminDep,
    db: AsyncSession = Depends(get_session),
) -> BoardApplicationOut:
    result = await review_application(db, app_id, _cur.id, body)
    await bump_collection_version("boards")
    return result


# 负责人
@router.patch("/{board_id}", response_model=ApiResp[BoardOut])
@respond
async def owner_update_board(
    board_id: int,
    patch: BoardUpdate,
    cur: CurrentUserDep,
    db: AsyncSession = Depends(get_session),
) -> BoardOut:
    result = await update_board_ex(db, board_id, cur.id, patch)
    await bump_collection_version("boards")
    await cache_invalidate(make_key("boards:item", board_id))
    return result


@router.post("/{board_id}/bans", response_model=ApiResp[dict[str, bool]])
@respond
async def ban(
    board_id: int,
    body: BanRequest,
    cur: CurrentUserDep,
    db: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    board = await get_board_ex(db, board_id)
    await ban_user(db, board, cur.id, body)
    return {"ok": True}


@router.delete(
    "/{board_id}/bans/{target_user_id}", response_model=ApiResp[dict[str, bool]]
)
@respond
async def unban(
    board_id: int,
    target_user_id: int,
    cur: CurrentUserDep,
    db: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    board = await get_board_ex(db, board_id)
    await unban_user(db, board, cur.id, target_user_id)
    return {"ok": True}
