from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResp(BaseModel, Generic[T]):
    code: int
    msg: str
    data: T | None = None


class ListData(BaseModel, Generic[T]):
    items: list[T]


class ModuleStatus(BaseModel):
    module: str
    status: str = "planned"
    responsibility: str
    next_steps: list[str]
