import asyncio
import json
import logging
from dataclasses import fields, is_dataclass
from typing import Any, AsyncIterator

from agents import (
    OpenAIChatCompletionsModel,
    Runner,
    SQLiteSession,
    set_tracing_disabled,
)
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.agent.context import AgentContext
from app.agent.models import AgentAnswer, AgentStreamEvent
from app.agent.workflow import build_agent
from app.config import OpenRouterSettings
from app.constants import AGENT_SESSION_DB_PATH, MAX_AGENT_TURNS, OPENROUTER_BASE_URL
from app.services.google_places import GooglePlacesService

logger = logging.getLogger(__name__)

# OpenAI tracing requires a separate OpenAI API key. This application uses
# OpenRouter only, so traces stay local in stdout for now.
set_tracing_disabled(True)


class AgentService:
    def __init__(
        self,
        settings: OpenRouterSettings,
        google_places: GooglePlacesService,
    ) -> None:
        self._settings = settings
        self._google_places = google_places

    async def stream(
        self, message: str, session_id: str
    ) -> AsyncIterator[AgentStreamEvent]:
        AGENT_SESSION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        session = SQLiteSession(session_id, AGENT_SESSION_DB_PATH)
        client = AsyncOpenAI(
            api_key=self._settings.api_key,
            base_url=OPENROUTER_BASE_URL,
            default_headers={"X-Title": "AskAround"},
        )
        result = None

        try:
            model = OpenAIChatCompletionsModel(
                model=self._settings.model,
                openai_client=client,
            )
            context = AgentContext(google_places=self._google_places)
            agent = build_agent(model)

            yield self._event(
                "agent_started",
                {
                    "agent": agent.name,
                    "model": self._settings.model,
                    "input": message,
                    "session_id": session_id,
                },
                log_event=False,
            )

            result = Runner.run_streamed(
                agent,
                message,
                context=context,
                max_turns=MAX_AGENT_TURNS,
                session=session,
            )
            async for stream_event in result.stream_events():
                converted = self._convert_sdk_event(
                    stream_event,
                    scope="agent",
                    agent_name=agent.name,
                )
                if converted is not None:
                    yield converted

            final_output = AgentAnswer.model_validate(result.final_output)
            yield self._event(
                "agent_completed",
                {"output": final_output.model_dump(mode="json")},
            )
        except asyncio.CancelledError:
            if result is not None:
                result.cancel()
            logger.info("Agent stream cancelled by the client")
            raise
        except Exception as exc:
            logger.exception("Agent run failed")
            yield self._event(
                "agent_error",
                {"error": type(exc).__name__, "detail": str(exc)},
            )
        finally:
            session.close()
            await client.close()

    @classmethod
    def _convert_sdk_event(
        cls,
        stream_event: Any,
        scope: str,
        agent_name: str,
    ) -> AgentStreamEvent | None:
        if stream_event is None:
            return None
        if stream_event.type == "raw_response_event":
            event_type = getattr(
                stream_event.data,
                "type",
                type(stream_event.data).__name__,
            )
            if event_type != "response.reasoning_text.done":
                return None
            thinking = str(getattr(stream_event.data, "text", "")).strip()
            if not thinking:
                return None
            return cls._event(
                "agent_thinking",
                {
                    "scope": scope,
                    "agent": agent_name,
                    "thinking": thinking,
                },
            )
        if stream_event.type == "run_item_stream_event":
            raw_item = getattr(stream_event.item, "raw_item", None)
            if stream_event.name == "tool_called":
                parameters = cls._parse_json_value(
                    cls._item_value(raw_item, "arguments", "")
                )
                return cls._event(
                    "tool_call",
                    {
                        "scope": scope,
                        "agent": agent_name,
                        "tool": cls._item_value(
                            raw_item,
                            "name",
                            "unknown_tool",
                        ),
                        "parameters": parameters,
                    },
                )
            if stream_event.name == "tool_output":
                return cls._event(
                    "tool_output",
                    {
                        "scope": scope,
                        "agent": agent_name,
                        "output": cls._parse_json_value(
                            cls._item_value(raw_item, "output", "")
                        ),
                    },
                )
        return None

    @staticmethod
    def _item_value(item: Any, key: str, default: Any = None) -> Any:
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    @staticmethod
    def _parse_json_value(value: Any) -> Any:
        if not isinstance(value, str):
            return AgentService._jsonable(value)
        stripped = value.strip()
        if not stripped:
            return ""
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return stripped

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        if is_dataclass(value) and not isinstance(value, type):
            return {
                field.name: AgentService._jsonable(getattr(value, field.name))
                for field in fields(value)
                if not field.name.startswith("_")
            }
        if isinstance(value, dict):
            return {key: AgentService._jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [AgentService._jsonable(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @staticmethod
    def _run_item_data(item: Any) -> dict[str, Any]:
        agent = getattr(item, "agent", None)
        return {
            "type": getattr(item, "type", type(item).__name__),
            "agent": getattr(agent, "name", None),
            "raw_item": AgentService._jsonable(getattr(item, "raw_item", None)),
        }

    @staticmethod
    def _is_delta_event(event_type: str) -> bool:
        return event_type.endswith(".delta")

    @staticmethod
    def _event(
        event: str,
        data: dict[str, Any],
        log_event: bool = True,
    ) -> AgentStreamEvent:
        stream_event = AgentStreamEvent(event=event, data=data)
        if log_event:
            logger.info(
                "Agent trace: %s",
                json.dumps(stream_event.model_dump(mode="json"), ensure_ascii=False),
            )
        return stream_event
