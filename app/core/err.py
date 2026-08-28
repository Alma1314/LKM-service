import functools
import logging
from collections.abc import Callable, Coroutine
from enum import IntEnum
from typing import Any, cast

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.modules.common import ApiResp, PageData

logger = logging.getLogger(__name__)


class Namespace:
    """Error-code namespace: encodes ns_id<<16 | local so modules stay collision-free."""

    ns_id: int
    prefix: str

    def __init__(self, ns_id: int, prefix: str) -> None:
        self.ns_id = ns_id
        self.prefix = prefix

    def err(self, local: int) -> int:
        return (self.ns_id << 16) | local


class ErrCode(IntEnum):
    """Base type for every module error-code enum."""


NS_COMMON = Namespace(0, "common")
NS_AUTH = Namespace(1, "auth")
NS_COLUMNS = Namespace(2, "columns")
NS_BLOG = Namespace(3, "blog")
NS_FORUM = Namespace(4, "forum")
NS_FILES = Namespace(5, "files")
NS_STARHOPE = Namespace(7, "starhope")
NS_ARTICLES = Namespace(8, "articles")
NS_STORAGE = Namespace(9, "storage")
NS_EXAM = Namespace(10, "exam")
NS_BOARDS = Namespace(11, "boards")
NS_POINTS = Namespace(12, "points")
NS_QA = Namespace(13, "qa")
NS_PROJECTS = Namespace(14, "projects")
NS_FOLLOW = Namespace(15, "follow")
NS_MODERATION = Namespace(16, "moderation")
NS_CONTENT = Namespace(17, "content")


class CommonErr(ErrCode):
    OK = 0
    INVALID_INPUT = NS_COMMON.err(1)
    FORBIDDEN = NS_COMMON.err(2)
    INTERNAL_ERROR = NS_COMMON.err(3)
    MFA_REQUIRED = NS_COMMON.err(4)  # 危险操作需重新完成 2FA（step-up）


ERRTABLE: dict[ErrCode, tuple[int, str]] = {}


def register(errors: dict[ErrCode, tuple[int, str]]) -> None:
    for code, info in errors.items():
        if code in ERRTABLE:
            raise ValueError(f"Duplicate error code: {code!r}")
        ERRTABLE[code] = info


register(
    {
        CommonErr.OK: (200, "OK"),
        CommonErr.INVALID_INPUT: (422, "Invalid input"),
        CommonErr.FORBIDDEN: (403, "Forbidden"),
        CommonErr.INTERNAL_ERROR: (500, "Internal server error"),
        CommonErr.MFA_REQUIRED: (401, "MFA required"),
    }
)


class BizError(Exception):
    errcode: ErrCode
    detail: str

    def __init__(self, errcode: ErrCode, detail: str | None = None) -> None:
        self.errcode = errcode
        self.detail = detail or ERRTABLE[errcode][1]


def map_err(exc: Exception) -> tuple[int, ErrCode, str]:
    if isinstance(exc, BizError):
        status, _ = ERRTABLE[exc.errcode]
        return status, exc.errcode, exc.detail

    if isinstance(exc, RequestValidationError):
        msgs: list[str] = []
        for err in exc.errors():
            field = ".".join(str(loc) for loc in err.get("loc", []) if loc != "body")
            msgs.append(f"{field}: {err.get('msg', '')}")
        detail = "; ".join(msgs)
        status, _ = ERRTABLE[CommonErr.INVALID_INPUT]
        return status, CommonErr.INVALID_INPUT, detail

    logger.error("Unhandled exception", exc_info=exc)
    status, msg = ERRTABLE[CommonErr.INTERNAL_ERROR]
    return status, CommonErr.INTERNAL_ERROR, msg


def resp_json(
    errcode: ErrCode,
    *,
    data: Any = None,
    detail: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    status, msg = ERRTABLE[errcode]

    return JSONResponse(
        status_code=status,
        content=ApiResp(code=errcode, msg=detail or msg, data=data).model_dump(
            mode="json"
        ),
        headers=headers,
    )


def respond[**P, R](
    func: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, JSONResponse]]:
    """装饰器：将返回值通过 ERRTABLE 包装。

    仅承担 FastAPI 端点（当前全部为 async def），返回类型保持 Coroutine 交给 FastAPI await。
    """

    @functools.wraps(func)
    async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> JSONResponse:
        result = await func(*args, **kwargs)
        return _wrap_result(result)

    return async_wrapper


def _wrap_result(result: Any) -> JSONResponse:
    if (
        isinstance(result, tuple)
        and len(cast(Any, result)) >= 2
        and isinstance(result[0], ErrCode)
    ):
        # isinstance 已收窄 result[0] 为 ErrCode，无需再 cast
        errcode = result[0]
        payload = result[1]
        if isinstance(payload, str):
            return resp_json(errcode, detail=payload)
        return resp_json(errcode, data=payload)
    extra: dict[str, str] = {}
    if isinstance(result, PageData):
        extra["X-Total"] = str(result.total)
    return resp_json(CommonErr.OK, data=result, headers=extra)
