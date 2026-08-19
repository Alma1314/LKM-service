from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.db.models import ExamQuestion


class QuestionCreate(BaseModel):
    kind: str = Field(..., pattern="^(single|judge)$")
    content: str = Field(..., min_length=1)
    options: list[dict[str, str]] = Field(default_factory=list)
    answer: str = Field(..., min_length=1, max_length=200)
    analysis: str | None = Field(default=None, max_length=2000)
    difficulty: int = Field(default=1, ge=1, le=3)
    score: int = Field(default=10, ge=1)
    sort_order: int = Field(default=0)


class QuestionOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    kind: str
    content: str
    options: list[dict[str, str]]
    answer: str
    analysis: str | None = None
    difficulty: int
    score: int
    sort_order: int

    @classmethod
    def from_model(cls, q: ExamQuestion) -> QuestionOut:
        """从 ORM 对象构造。因 ``options`` 在 DB 是 JSON 文本列，不能用
        ``model_validate`` 自动转换（会把字符串塞进 list 报错），改显式 dict。"""
        import json

        return cls(
            id=q.id,
            kind=q.kind,
            content=q.content,
            options=json.loads(q.options or "[]"),
            answer=q.answer,
            analysis=q.analysis,
            difficulty=q.difficulty,
            score=q.score,
            sort_order=q.sort_order,
        )


class ExamCreate(BaseModel):
    type: str = Field(default="exam", pattern="^(exam|competition)$")
    title: str = Field(..., min_length=1, max_length=200)
    subject: str = Field(default="", max_length=50)
    difficulty: int = Field(default=1, ge=1, le=3)
    description: str | None = Field(default=None, max_length=2000)
    pass_score: int = Field(default=60, ge=1)
    time_limit_min: int = Field(default=30, ge=1)
    unlock_level: str | None = Field(default=None, pattern="^(local|normal|admin)$")
    unlock_role: str | None = Field(default=None, max_length=20)
    starts_at: datetime.datetime | None = None
    ends_at: datetime.datetime | None = None
    questions: list[QuestionCreate] = Field(default_factory=list)


class ExamOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    type: str
    title: str
    subject: str
    difficulty: int
    description: str | None = None
    pass_score: int
    time_limit_min: int
    is_published: bool
    unlock_level: str | None = None
    unlock_role: str | None = None
    starts_at: datetime.datetime | None = None
    ends_at: datetime.datetime | None = None
    question_count: int = 0
    created_at: datetime.datetime
    updated_at: datetime.datetime


class QuestionForAttempt(BaseModel):
    """开考时下发给考生的题目（客户端安全 DTO）。

    刻意省略 answer / analysis，防止考生在作答前就拿到正确答案——否则任何交卷
    都能满分，认证判分与竞赛榜单将失去意义。答案仅留在服务端 exam.questions 供判分。
    """

    id: int
    kind: str
    content: str
    options: list[dict[str, str]]
    difficulty: int
    score: int
    sort_order: int


class AttemptStartResp(BaseModel):
    attempt_id: int
    exam_id: int
    questions: list[QuestionForAttempt]
    time_limit_min: int
    deadline: datetime.datetime | None = None


class SubmitAnswersRequest(BaseModel):
    answers: dict[int, str] = Field(default_factory=dict)


class SubmitResult(BaseModel):
    attempt_id: int
    exam_id: int
    score: int
    pass_score: int
    passed: bool
    unlock_level: str | None = None
    unlock_role: str | None = None
    certificate_id: int | None = None


class CertificateOut(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: int
    exam_id: int
    user_id: int
    exam_title: str = ""
    score: int
    passed: bool
    cert_no: str
    issued_at: datetime.datetime


class LeaderboardEntry(BaseModel):
    user_id: int
    display_name: str
    score: int
    certified: bool = False
