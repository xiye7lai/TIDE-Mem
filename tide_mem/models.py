from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MemoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1)
    content: str = Field(min_length=1)
    timestamp: int | None = Field(default=None, ge=0)

    @field_validator("role")
    @classmethod
    def strip_role(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("role must not be blank")
        return value

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content must not be blank")
        return value


class AddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    messages: list[MemoryMessage] = Field(min_length=1)
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)


class AddResponse(BaseModel):
    success: Literal[True] = True
    request_id: str
    user_id: str
    session_id: str


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    options: list[str] | None = None
    user_id: str = Field(min_length=1)
    top_k: int = Field(ge=1)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value


class SearchItem(BaseModel):
    id: str
    content: str
    score: float | None = None
    created_at: str | None = None


class SearchResponse(BaseModel):
    data: list[SearchItem]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    system: str
    version: str
    llm_model: str
    llm_mode: str
