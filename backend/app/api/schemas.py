from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,64}$")
    department: str | None = Field(default=None, pattern=r"^[A-Z]{2,5}$", description="e.g. HS, OPS, LP, CS")


class Source(BaseModel):
    ref: int
    sop_id: str
    title: str
    section: str
    version: str
    department: str
    page: int | None = None
    snippet: str
    score: float
    cited: bool


class GuardrailInfo(BaseModel):
    input: Literal["passed", "anonymized", "blocked"]
    output: Literal["passed", "anonymized", "blocked", "skipped"]


class ChatResponse(BaseModel):
    message_id: str
    session_id: str
    answer: str
    sources: list[Source]
    guardrails: GuardrailInfo
    latency_ms: int


class FeedbackRequest(BaseModel):
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    message_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=500)
