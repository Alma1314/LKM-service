"""板块服务：Board CRUD、板块申请、禁言、发言准入校验。"""

import datetime

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import BizError
from app.db.models import (
    Board,
    BoardApplication,
    BoardBan,
    Exam,
    ExamCertificate,
    User,
    now_iso,
)
from app.db.repo import get_or_raise
from app.modules.content.errors import BoardErr
from app.modules.content.boards_schemas import (
    BanRequest,
    BoardApplicationCreate,
    BoardApplicationOut,
    BoardCreate,
    BoardOut,
    BoardUpdate,
    ReviewBoardApplicationRequest,
)


def _board_to_schema(b: Board) -> BoardOut:
    return BoardOut.model_validate(b)


def _application_to_schema(a: BoardApplication) -> BoardApplicationOut:
    return BoardApplicationOut.model_validate(a)


# ————— Board CRUD —————
async def create_board_ex(
    db: AsyncSession, info: BoardCreate, owner_id: int | None
) -> BoardOut:
    conflict = await db.scalar(select(Board.id).where(Board.slug == info.slug))
    if conflict is not None:
        raise BizError(BoardErr.SLUG_CONFLICT)
    board = Board(
        slug=info.slug,
        title=info.title,
        description=info.description,
        owner_id=owner_id,
        parent_id=info.parent_id,
        require_certified=info.require_certified,
        daily_post_limit=info.daily_post_limit,
        is_public=info.is_public,
    )
    db.add(board)
    await db.flush()
    return _board_to_schema(board)


async def list_boards(db: AsyncSession) -> list[BoardOut]:
    rows = (await db.execute(select(Board).order_by(Board.id.asc()))).scalars().all()
    return [_board_to_schema(b) for b in rows]


async def get_board_ex(db: AsyncSession, board_id: int) -> Board:
    return await get_or_raise(db, Board, BoardErr.BOARD_NOT_FOUND, Board.id == board_id)


async def update_board_ex(
    db: AsyncSession,
    board_id: int,
    owner_id: int,
    patch: BoardUpdate,
    *,
    is_admin: bool = False,
) -> BoardOut:
    board = await get_board_ex(db, board_id)
    _assert_owner(board, owner_id, is_admin)
    data = patch.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(board, k, v)
    await db.flush()
    return _board_to_schema(board)


def _assert_owner(board: Board, current_user_id: int, is_admin: bool = False) -> None:
    # 防御性断言：非属主且非 admin(代管) → 拒。路由层 check_owner 已先做对象级
    # 判定(board_owner_manage)，此处 is_admin 由路由传 cur.role=="super_admin" 放行代管。
    if board.owner_id != current_user_id and not is_admin:
        raise BizError(BoardErr.NOT_BOARD_OWNER)


# ————— 板块申请/审核 —————
async def submit_application(
    db: AsyncSession, applicant_id: int, info: BoardApplicationCreate
) -> BoardApplicationOut:
    # slug 为全局唯一命名空间：既不能与已存在的板块冲突，也不能与待审申请冲突
    conflict = await db.scalar(
        select(BoardApplication.id).where(BoardApplication.slug == info.slug)
    )
    if conflict is not None:
        raise BizError(BoardErr.SLUG_CONFLICT)
    board_conflict = await db.scalar(select(Board.id).where(Board.slug == info.slug))
    if board_conflict is not None:
        raise BizError(BoardErr.SLUG_CONFLICT)
    app_ = BoardApplication(
        applicant_id=applicant_id,
        title=info.title,
        description=info.description,
        reason=info.reason,
        slug=info.slug,
        status="pending",
    )
    db.add(app_)
    await db.flush()
    return _application_to_schema(app_)


async def review_application(
    db: AsyncSession,
    application_id: int,
    reviewer_id: int,
    body: ReviewBoardApplicationRequest,
) -> BoardApplicationOut:
    app_ = await get_or_raise(
        db,
        BoardApplication,
        BoardErr.APPLICATION_NOT_FOUND,
        BoardApplication.id == application_id,
    )
    if app_.status != "pending":
        raise BizError(BoardErr.APPLICATION_ALREADY_REVIEWED)
    if body.approve:
        # 通过前先核对该申请 slug 是否已被现有 Board 占用；若占用则提前报冲突，
        # 不修改申请状态，避免状态被标记 approved/reviewed 却未真正创建板块的不一致局面。
        board_conflict = await db.scalar(
            select(Board.id).where(Board.slug == app_.slug)
        )
        if board_conflict is not None:
            raise BizError(BoardErr.SLUG_CONFLICT)
    app_.status = "approved" if body.approve else "rejected"
    app_.reviewer_id = reviewer_id
    app_.review_note = body.note
    app_.reviewed_at = now_iso()
    await db.flush()
    if body.approve:
        # 通过则创建板块并把申请人设为负责人；slug 若被占用则报冲突（罕见、明确）
        await create_board_ex(
            db,
            BoardCreate(
                slug=app_.slug,
                title=app_.title,
                description=app_.description,
            ),
            owner_id=app_.applicant_id,
        )
    return _application_to_schema(app_)


# ————— 禁言 —————
async def ban_user(
    db: AsyncSession,
    board: Board,
    actor_id: int,
    body: BanRequest,
    *,
    is_admin: bool = False,
) -> None:
    _assert_owner(board, actor_id, is_admin)
    already = await db.scalar(
        select(BoardBan.id).where(
            BoardBan.board_id == board.id,
            BoardBan.user_id == body.user_id,
            BoardBan.expires_at > now_iso(),
        )
    )
    if already is not None:
        raise BizError(BoardErr.ALREADY_BANNED)
    db.add(
        BoardBan(
            board_id=board.id,
            user_id=body.user_id,
            created_by=actor_id,
            reason=body.reason,
            expires_at=now_iso() + datetime.timedelta(hours=body.hours),
        )
    )
    await db.flush()


async def unban_user(
    db: AsyncSession,
    board: Board,
    actor_id: int,
    target_user_id: int,
    *,
    is_admin: bool = False,
) -> None:
    _assert_owner(board, actor_id, is_admin)
    await db.execute(
        sa_delete(BoardBan).where(
            BoardBan.board_id == board.id,
            BoardBan.user_id == target_user_id,
        )
    )
    await db.flush()


async def is_banned(db: AsyncSession, board_id: int, user_id: int) -> bool:
    row = await db.scalar(
        select(BoardBan.id).where(
            BoardBan.board_id == board_id,
            BoardBan.user_id == user_id,
            BoardBan.expires_at > now_iso(),
        )
    )
    return row is not None


# ————— 发言准入（供 forum create_post 调用）—————
async def check_post_allowed(db: AsyncSession, board_id: int, user_id: int) -> None:
    """校验用户在板块的发帖资格：板块存在 / 可见 / 未禁言 / 认证 / 日限发。异常抛相应 BoardErr。"""
    board = await get_board_ex(db, board_id)
    if not board.is_public:
        # 私有板块：需 normal 以上（认证成员）
        ulevel = await db.scalar(select(User.account_level).where(User.id == user_id))
        if ulevel not in ("normal", "admin"):
            raise BizError(BoardErr.BOARD_NOT_PUBLIC)
    if await is_banned(db, board.id, user_id):
        raise BizError(BoardErr.BOARD_BANNED)
    if board.require_certified:
        passed = await db.scalar(
            select(ExamCertificate.id)
            .join(Exam, Exam.id == ExamCertificate.exam_id)
            .where(
                # 初级通识考试通过判定：证书来自 type=exam 且 unlock_level=normal 的认证考试
                ExamCertificate.user_id == user_id,
                ExamCertificate.passed.is_(True),
                Exam.type == "exam",
                Exam.unlock_level == "normal",
            )
            .limit(1)
        )
        if passed is None:
            raise BizError(BoardErr.CERTIFICATION_REQUIRED)
    if board.daily_post_limit > 0:
        from app.db.models import ContentItem, ContentType

        today_start = now_iso().replace(hour=0, minute=0, second=0, microsecond=0)
        cnt = (
            await db.scalar(
                select(func.count(ContentItem.id)).where(
                    ContentItem.author_id == user_id,
                    ContentItem.board_id == board_id,
                    ContentItem.content_type == ContentType.DISCUSSION,
                    ContentItem.created_at >= today_start,
                )
            )
            or 0
        )
        if cnt >= board.daily_post_limit:
            raise BizError(BoardErr.DAILY_POST_LIMIT_REACHED)
