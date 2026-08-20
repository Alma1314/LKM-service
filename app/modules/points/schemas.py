import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class BalanceOut(BaseModel):
    user_id: int
    balance: int


class LedgerEntry(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    delta: int
    balance_after: int
    reason: str
    ref_type: str
    ref_id: str
    created_at: datetime.datetime


class LeaderboardEntry(BaseModel):
    user_id: int
    display_name: str
    balance: int
