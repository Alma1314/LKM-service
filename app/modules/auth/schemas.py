from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field
from pydantic_core import core_schema


class ProfileRole(StrEnum):
    MEMBER = "member"
    ADMIN = "admin"


class Password(str):
    @classmethod
    def validate(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
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
