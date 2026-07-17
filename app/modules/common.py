from pydantic import BaseModel


class ApiResp(BaseModel):
    code: int
    msg: str
    data: dict | None = None


class ModuleStatus(BaseModel):
    module: str
    status: str = "planned"
    responsibility: str
    next_steps: list[str]
