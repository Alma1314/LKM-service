import inspect
import functools
from enum import IntEnum

from fastapi.exceptions import RequestValidationError


class ErrCode(IntEnum):
    OK = 0
    INVALID_INPUT = 1001
    ALREADY_REGISTERED = 1002
    INVALID_CREDENTIALS = 1003
    USER_NOT_FOUND = 1004
    FORBIDDEN = 1005
    ACCOUNT_LOCKED = 1006
    ACCOUNT_LEVEL_INSUFFICIENT = 1007
    VERIFICATION_CODE_INVALID = 1008
    VERIFICATION_CODE_EXPIRED = 1009
    VERIFICATION_CODE_RATE_LIMIT = 1010
    TOKEN_EXPIRED = 1011
    TOKEN_INVALID = 1012
    REFRESH_TOKEN_REVOKED = 1013
    TOTP_NOT_ENABLED = 1101
    TOTP_ALREADY_ENABLED = 1102
    TOTP_SETUP_REQUIRED = 1103
    TOTP_CODE_INVALID = 1104
    RECOVERY_CODE_INVALID = 1105
    RECOVERY_CODE_USED = 1106
    OAUTH_CANCELED = 1201
    OAUTH_PROVIDER_ERROR = 1202
    OAUTH_EMAIL_TAKEN = 1203
    PASSKEY_REGISTRATION_FAILED = 1301
    PASSKEY_VERIFICATION_FAILED = 1302
    RECOVERY_NOT_SUPPORTED = 1401
    RECOVERY_METHOD_UNAVAILABLE = 1402
    COLUMN_APPLICATION_NOT_FOUND = 2001
    COLUMN_NOT_FOUND = 2002
    COLUMN_POST_NOT_FOUND = 2003
    BLOG_SERIES_NOT_FOUND = 3001
    BLOG_COMMENT_NOT_FOUND = 3002
    BLOG_GIT_ERROR = 3003
    INTERNAL_ERROR = 9999


ERRTABLE: dict[ErrCode, tuple[int, str]] = {
    ErrCode.OK:                           (200, "OK"),
    ErrCode.INVALID_INPUT:                (422, "Invalid input"),
    ErrCode.ALREADY_REGISTERED:           (400, "Username or email already registered"),
    ErrCode.INVALID_CREDENTIALS:          (401, "Invalid username or password"),
    ErrCode.USER_NOT_FOUND:               (401, "User not found"),
    ErrCode.FORBIDDEN:                    (403, "Forbidden"),
    ErrCode.ACCOUNT_LOCKED:               (423, "Account is locked"),
    ErrCode.ACCOUNT_LEVEL_INSUFFICIENT:   (403, "Account level insufficient"),
    ErrCode.VERIFICATION_CODE_INVALID:    (400, "Verification code invalid"),
    ErrCode.VERIFICATION_CODE_EXPIRED:    (400, "Verification code expired"),
    ErrCode.VERIFICATION_CODE_RATE_LIMIT: (429, "Verification code rate limit exceeded"),
    ErrCode.TOKEN_EXPIRED:                (401, "Token expired"),
    ErrCode.TOKEN_INVALID:                (401, "Token invalid"),
    ErrCode.REFRESH_TOKEN_REVOKED:        (401, "Refresh token revoked"),
    ErrCode.TOTP_NOT_ENABLED:             (400, "TOTP not enabled"),
    ErrCode.TOTP_ALREADY_ENABLED:         (400, "TOTP already enabled"),
    ErrCode.TOTP_SETUP_REQUIRED:          (400, "TOTP setup required"),
    ErrCode.TOTP_CODE_INVALID:            (400, "TOTP code invalid"),
    ErrCode.RECOVERY_CODE_INVALID:        (400, "Recovery code invalid"),
    ErrCode.RECOVERY_CODE_USED:           (400, "Recovery code already used"),
    ErrCode.OAUTH_CANCELED:               (400, "OAuth login canceled"),
    ErrCode.OAUTH_PROVIDER_ERROR:         (502, "OAuth provider error"),
    ErrCode.OAUTH_EMAIL_TAKEN:            (409, "OAuth email already taken"),
    ErrCode.PASSKEY_REGISTRATION_FAILED:  (400, "Passkey registration failed"),
    ErrCode.PASSKEY_VERIFICATION_FAILED:  (400, "Passkey verification failed"),
    ErrCode.RECOVERY_NOT_SUPPORTED:       (400, "Recovery not supported"),
    ErrCode.RECOVERY_METHOD_UNAVAILABLE:  (400, "Recovery method unavailable"),
    ErrCode.COLUMN_APPLICATION_NOT_FOUND: (404, "Column application not found"),
    ErrCode.COLUMN_NOT_FOUND:             (404, "Column not found"),
    ErrCode.COLUMN_POST_NOT_FOUND:        (404, "Column post not found"),
    ErrCode.BLOG_SERIES_NOT_FOUND:        (404, "Blog series not found"),
    ErrCode.BLOG_COMMENT_NOT_FOUND:       (404, "Comment not found"),
    ErrCode.BLOG_GIT_ERROR:               (500, "Git operation failed"),
    ErrCode.INTERNAL_ERROR:               (500, "Internal server error"),
}


class BizError(Exception):
    def __init__(self, errcode: ErrCode, detail: str | None = None):
        self.errcode = errcode
        self.detail = detail or ERRTABLE[errcode][1]


def map_err(exc: Exception) -> tuple[int, ErrCode, str]:
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


def resp_json(errcode: ErrCode, *, data=None, detail=None):
    status, msg = ERRTABLE[errcode]
    from fastapi.responses import JSONResponse

    from app.modules.common import ApiResp

    return JSONResponse(
        status_code=status,
        content=ApiResp(code=errcode, msg=detail or msg, data=data).model_dump(),
    )


def respond(func):
    """装饰器：将返回值通过 ERRTABLE 包装。 """

    if inspect.iscoroutinefunction(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)
            return _wrap_result(result)

        return async_wrapper

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        return _wrap_result(result)

    return sync_wrapper


def _wrap_result(result):
    if isinstance(result, tuple) and isinstance(result[0], ErrCode):
        errcode, payload = result
        if isinstance(payload, str):
            return resp_json(errcode, detail=payload)
        return resp_json(errcode, data=payload)
    return resp_json(ErrCode.OK, data=result)
