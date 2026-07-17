from enum import IntEnum

from fastapi.exceptions import RequestValidationError


class ErrCode(IntEnum):
    OK = 0
    INVALID_INPUT = 1001
    ALREADY_REGISTERED = 1002
    INTERNAL_ERROR = 9999


# (http_status, default_message)
ERRTABLE: dict[ErrCode, tuple[int, str]] = {
    ErrCode.OK:                 (200, "OK"),
    ErrCode.INVALID_INPUT:      (422, "Invalid input"),
    ErrCode.ALREADY_REGISTERED: (400, "Username or email already registered"),
    ErrCode.INTERNAL_ERROR:     (500, "Internal server error"),
}


class BizError(Exception):
    def __init__(self, errcode: ErrCode, detail: str | None = None):
        self.errcode = errcode
        self.detail = detail or ERRTABLE[errcode][1]


def map_err(exc: Exception) -> tuple[int, int, str]:
    """Dispatch exception -> (http_status, errcode, detail)."""
    if isinstance(exc, BizError):
        status, _ = ERRTABLE[exc.errcode]
        return status, exc.errcode, exc.detail

    if isinstance(exc, RequestValidationError):
        msgs = []
        for err in exc.errors():
            field = ".".join(str(loc) for loc in err["loc"] if loc != "body")
            msgs.append(f"{field}: {err['msg']}")
        detail = "; ".join(msgs)
        status, _ = ERRTABLE[ErrCode.INVALID_INPUT]
        return status, ErrCode.INVALID_INPUT, detail

    status, msg = ERRTABLE[ErrCode.INTERNAL_ERROR]
    return status, ErrCode.INTERNAL_ERROR, msg
