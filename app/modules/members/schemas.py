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


class SubGroupItem(SubGroup):
    """带 key 的子组结构，用于一次性返回整组 subGroupMaps。"""

    key: str
