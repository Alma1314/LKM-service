from enum import IntEnum


class ErrCode(IntEnum):
    """Application error codes. 0 = success, non-zero = error."""

    OK = 0
    INVALID_INPUT = 1001
    ALREADY_REGISTERED = 1002
    DB_ERROR = 2001
    INTERNAL_ERROR = 9999

    def msg(self) -> str:
        _msgs = {
            ErrCode.OK: "OK",
            ErrCode.INVALID_INPUT: "Invalid input",
            ErrCode.ALREADY_REGISTERED: "Username or email already registered",
            ErrCode.DB_ERROR: "Database error",
            ErrCode.INTERNAL_ERROR: "Internal server error",
        }
        return _msgs.get(self, "Unknown error")


class BizError(Exception):
    """Business exception carrying an ErrCode."""

    def __init__(self, errcode: ErrCode, detail: str | None = None):
        self.errcode = errcode
        self.detail = detail or errcode.msg()
