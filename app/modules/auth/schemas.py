import enum
from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field
from pydantic_core import core_schema


class ProfileRole(StrEnum):
    MEMBER = "member"
    ADMIN = "admin"


class Password(str):
    @classmethod
    def validate(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters")
        return v

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        return core_schema.no_info_after_validator_function(
            cls.validate,
            handler(str),
        )


class UserRegInfo(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: Password = Field(...)


class UserLoginInfo(BaseModel):
    username: str = Field(..., min_length=1)
    password: str


class ProfileInfo(BaseModel):
    nickname: str | None = None
    avatar: str | None = None
    role: ProfileRole = ProfileRole.MEMBER


class ProfileUpdate(BaseModel):
    nickname: str | None = None
    avatar: str | None = None


class UserIdData(BaseModel):
    user_id: int

class AccountLevel(str, enum.Enum):
    LOCAL = "local"
    NORMAL = "normal"
    ADMIN = "admin"


class UserRegLocal(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: Password = Field(...)


class UserRegNormal(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: Password = Field(...)
    email: EmailStr | None = None
    phone: str | None = Field(None, min_length=5, max_length=20)


class UserRegByPhone(BaseModel):
    phone: str = Field(..., min_length=5, max_length=20)


class UserRegByEmail(BaseModel):
    email: EmailStr


class UserLoginPassword(BaseModel):
    account: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class AuthTokenData(BaseModel):
    access_token: str | None = None
    refresh_token: str | None = None
    user_id: int
    account_level: str
    requires_2fa: bool = False
    setup_required: bool = False
    temp_token: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str

class TOTPSetupBeginData(BaseModel):
    secret: str
    qr_code_uri: str


class TOTPSetupCompleteRequest(BaseModel):
    code: str


class TOTPSetupCompleteData(BaseModel):
    recovery_codes: list[str]
    confirmed_saved_required: bool


class TOTPSetupCompleteTempData(BaseModel):
    """管理员强制设置的响应 — 包含认证令牌。"""
    recovery_codes: list[str]
    confirmed_saved_required: bool
    access_token: str | None = None
    refresh_token: str | None = None


class TOTPVerifyRequest(BaseModel):
    temp_token: str
    code: str | None = None
    recovery_code: str | None = None
    trust_device: bool = False


class TOTPDisableRequest(BaseModel):
    code: str
