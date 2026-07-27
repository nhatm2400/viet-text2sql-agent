"""Tools the agent may call. Each one is independently safe.

`ToolResult` is the single return shape for every tool. Two reasons it is not just a string:
the trace store writes `result` as JSONB, and the agent needs a machine-readable `status` to
decide whether to retry, rephrase or give up — free-text error messages make that decision
guesswork.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ToolStatus = Literal["ok", "blocked", "error", "needs_clarification", "not_implemented"]


class ToolResult(BaseModel):
    """Structured result of a single tool call."""

    status: ToolStatus = "ok"
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    error_kind: str | None = None
    """One of: syntax | permission | timeout | empty_result | policy | internal — lets the agent
    pick a recovery strategy instead of retrying the same SQL verbatim."""

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


def ok(message: str = "", **data: Any) -> ToolResult:
    return ToolResult(status="ok", message=message, data=data)


def blocked(message: str, *, error_kind: str = "policy", **data: Any) -> ToolResult:
    return ToolResult(status="blocked", message=message, data=data, error_kind=error_kind)


def error(message: str, *, error_kind: str = "internal", **data: Any) -> ToolResult:
    return ToolResult(status="error", message=message, data=data, error_kind=error_kind)


__all__ = ["ToolResult", "ToolStatus", "blocked", "error", "ok"]
