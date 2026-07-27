"""Model provider adapter: anthropic | openai_compatible | bedrock | offline.

`OFFLINE_MODE=1` swaps the real model for `OfflineProvider`, a `BaseChatModel` that replays a
scripted sequence of tool calls from `tests/fixtures/offline_llm.json`. That is what makes CI,
`make test`, `make demo-offline` and `make smoke` run with zero API keys, zero network and zero
database — and it replays a *multi-turn* script (including a failed `execute_sql` followed by a
corrected retry), so the offline path exercises the agent loop rather than a single call.

The provider SDK packages (`langchain-anthropic`, `langchain-openai`, `langchain-aws`) are
deliberately NOT hard dependencies: the offline path must install and run without them. They are
imported lazily and a missing one produces an install hint, not a traceback.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from t2sql.config import ModelRole, get_settings

FIXTURE_FILE = "offline_llm.json"


def question_key(question: str) -> str:
    """Stable key for a question: lowercased, whitespace-collapsed, sha1-truncated.

    Diacritics are preserved — "doanh thu" and "doanh so" are different questions and must not
    collapse onto the same fixture.
    """
    normalised = re.sub(r"\s+", " ", (question or "").strip().lower())
    return hashlib.sha1(normalised.encode("utf-8")).hexdigest()[:12]


@lru_cache(maxsize=1)
def load_fixtures(path: str | None = None) -> dict[str, Any]:
    """Load the offline script file and index it by question key and by id."""
    target = Path(path) if path else get_settings().fixtures_path / FIXTURE_FILE
    raw = json.loads(target.read_text(encoding="utf-8"))
    index: dict[str, Any] = {}
    for script in raw.get("scripts", []):
        index[script["id"]] = script
        index[question_key(script["question"])] = script
        for alias in script.get("aliases", []):
            index[question_key(alias)] = script
    return {"index": index, "default": raw.get("default"), "raw": raw}


class OfflineProvider(BaseChatModel):
    """Deterministic fixture replay. Requires no keys, no network and no database.

    Turn selection is a pure function of the conversation so far: the number of AI messages
    already in `messages` is the index into the script's `turns`. That means the same question
    always produces the same trace, which is what makes offline evaluation numbers meaningful.
    """

    fixtures_path: str | None = None
    role: str = "fast"

    @property
    def _llm_type(self) -> str:
        return "offline-fixture"

    def bind_tools(self, tools: Any, **kwargs: Any) -> OfflineProvider:  # noqa: ARG002
        """Accept the tool schemas and ignore them — the script already decided the calls."""
        return self

    @staticmethod
    def _first_question(messages: list[BaseMessage]) -> str:
        for message in messages:
            if isinstance(message, HumanMessage):
                return str(message.content)
        return ""

    def _script_for(self, question: str) -> dict[str, Any]:
        fixtures = load_fixtures(self.fixtures_path)
        script = fixtures["index"].get(question_key(question))
        if script is None:
            script = fixtures["default"]
        if script is None:
            raise KeyError(
                f"no offline fixture for question {question!r} (key={question_key(question)}). "
                f"Add a script to tests/fixtures/{FIXTURE_FILE}."
            )
        return script

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,  # noqa: ARG002
        run_manager: CallbackManagerForLLMRun | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ChatResult:
        question = self._first_question(messages)
        script = self._script_for(question)
        turns: list[dict[str, Any]] = script["turns"]

        turn_index = sum(1 for m in messages if isinstance(m, AIMessage))
        if turn_index >= len(turns):
            # Script exhausted. `repeat_last` scripts (used by test_max_iterations) intentionally
            # loop forever so the graph's iteration cap is what stops the run, not the fixture.
            if script.get("repeat_last"):
                turn = turns[-1]
            else:
                turn = {"content": "Không đủ thông tin để trả lời an toàn."}
        else:
            turn = turns[turn_index]

        tool_calls = [
            {"name": call["name"], "args": call.get("args", {}), "id": f"call_{turn_index}_{i}"}
            for i, call in enumerate(turn.get("tool_calls", []))
        ]
        message = AIMessage(content=turn.get("content", ""), tool_calls=tool_calls)
        return ChatResult(generations=[ChatGeneration(message=message)])


def get_model(role: ModelRole = "fast", **overrides: Any) -> BaseChatModel:
    """Return the chat model for `role`, honouring OFFLINE_MODE and MODEL_PROVIDER."""
    settings = get_settings()
    if settings.offline_mode:
        return OfflineProvider(role=role)

    name = settings.model_name(role)
    common: dict[str, Any] = {
        "temperature": settings.model_temperature,
        "max_tokens": settings.model_max_tokens,
        **overrides,
    }

    provider: Literal["anthropic", "openai_compatible", "bedrock"] = settings.model_provider
    try:
        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(model=name, api_key=settings.anthropic_api_key or None, **common)
        if provider == "openai_compatible":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=name,
                api_key=settings.openai_api_key or None,
                base_url=settings.openai_base_url or None,
                **common,
            )
        from langchain_aws import ChatBedrockConverse

        common.pop("max_tokens", None)
        return ChatBedrockConverse(
            model=name,
            region_name=settings.aws_region or None,
            max_tokens=settings.model_max_tokens,
            **common,
        )
    except ImportError as err:  # pragma: no cover - depends on optional extras
        package = {
            "anthropic": "langchain-anthropic",
            "openai_compatible": "langchain-openai",
            "bedrock": "langchain-aws",
        }[provider]
        raise RuntimeError(
            f"MODEL_PROVIDER={provider} needs `pip install {package}`. "
            "Offline runs (OFFLINE_MODE=1) require none of these."
        ) from err
