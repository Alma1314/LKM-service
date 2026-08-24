"""自动审校规则 CRUD 请求/响应模型。"""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class RuleCreate(BaseModel):
    pattern: str = Field(min_length=1, max_length=255)
    is_regex: bool = False
    action: str = "derank"  # derank | hide
    weight: float = Field(default=0.5, ge=0.0, le=1.0)
    scope: str = "content"
    enabled: bool = True


class RuleUpdate(BaseModel):
    pattern: str | None = Field(default=None, min_length=1, max_length=255)
    is_regex: bool | None = None
    action: str | None = None
    weight: float | None = Field(default=None, ge=0.0, le=1.0)
    scope: str | None = None
    enabled: bool | None = None


class RuleInfo(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    pattern: str
    is_regex: bool
    action: str
    weight: float
    scope: str
    enabled: bool
