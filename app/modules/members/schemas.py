from pydantic import BaseModel


class Member(BaseModel):
    name: str | None = None
    avatarKey: str | None = None
    role: str | None = None
    desc: str | None = None
    dream: str | None = None
    quote: str | None = None


class SubGroup(BaseModel):
    label: str
    desc: str | None = None
    members: list[Member]
