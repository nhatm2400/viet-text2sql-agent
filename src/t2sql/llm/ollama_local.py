"""Local-only Ollama adapter. No API keys, paid endpoints or extra SDK dependencies."""

from __future__ import annotations

import json
import urllib.request
import uuid
from typing import Any
from urllib.parse import urlparse

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field


def request_json(base_url: str, path: str, payload: dict | None = None, timeout: int = 180) -> dict:
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Local evaluation requires a loopback HTTP Ollama endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Credentials/query parameters are not accepted")
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
    )

    # Do not send local prompts through a configured corporate proxy or follow redirects.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError("Redirects are forbidden for local evaluation")

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        return json.load(response)


class OllamaLocal(BaseChatModel):
    model_name: str = "qwen3:4b"
    base_url: str = "http://127.0.0.1:11434"
    temperature: float = 0
    num_ctx: int = 8192
    num_predict: int = 2048
    seed: int = 42
    tool_schemas: list[dict] = Field(default_factory=list)
    audit: list[dict] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "ollama-local-live"

    def bind_tools(self, tools: Any, **kwargs: Any) -> OllamaLocal:
        return self.model_copy(update={"tool_schemas": [convert_to_openai_tool(t) for t in tools]})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        history = []
        for message in messages:
            role = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}[
                message.type
            ]
            entry = {"role": role, "content": message.content}
            if isinstance(message, AIMessage) and message.tool_calls:
                entry["tool_calls"] = [
                    {"function": {"name": c["name"], "arguments": c["args"]}}
                    for c in message.tool_calls
                ]
            if isinstance(message, ToolMessage):
                entry["tool_name"] = message.name or "execute_sql"
            history.append(entry)
        payload = {
            "model": self.model_name,
            "messages": history,
            "stream": False,
            "think": True,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
                "seed": self.seed,
            },
        }
        if self.tool_schemas:
            payload["tools"] = self.tool_schemas
        raw = request_json(self.base_url, "/api/chat", payload)
        self.audit.append(raw)
        response = raw["message"]
        calls = [
            {
                "id": uuid.uuid4().hex,
                "name": c["function"]["name"],
                "args": c["function"]["arguments"],
            }
            for c in response.get("tool_calls", [])
        ]
        usage = None
        if "prompt_eval_count" in raw and "eval_count" in raw:
            usage = {
                "input_tokens": raw["prompt_eval_count"],
                "output_tokens": raw["eval_count"],
                "total_tokens": raw["prompt_eval_count"] + raw["eval_count"],
            }
        message = AIMessage(
            content=response.get("content", ""),
            tool_calls=calls,
            usage_metadata=usage,
            response_metadata={"done_reason": raw.get("done_reason"), "model": raw.get("model")},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])
