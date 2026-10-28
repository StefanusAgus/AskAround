import asyncio
from contextlib import suppress
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
from app.agent.workflow import build_manager_agent
from app.config import OpenRouterSettings
from app.constants import (
    AGENT_SESSION_DB_PATH,
    MAX_MANAGER_AGENT_TURNS,
    MAX_MANAGER_PROGRESS_RETRIES,
    OPENROUTER_BASE_URL,
)
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
        producer_task: asyncio.Task[None] | None = None

        try:
            model = OpenAIChatCompletionsModel(
                model=self._settings.model,
                openai_client=client,
            )
            event_queue: asyncio.Queue[AgentStreamEvent | None] = asyncio.Queue()

            async def on_places_stream(payload: dict[str, Any]) -> None:
                nested_agent = payload.get("agent")
                stream_event = payload.get("event")
                converted = self._convert_sdk_event(
                    stream_event,
                    scope="places_agent",
                    agent_name=getattr(
                        nested_agent,
                        "name",
                        "Places Specialist",
                    ),
                )
                if converted is not None:
                    await event_queue.put(converted)

            workflow_context = AgentContext(google_places=self._google_places)
            agent = build_manager_agent(model, on_places_stream)

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

            attempt_input = message
            final_output = None
            for attempt in range(MAX_MANAGER_PROGRESS_RETRIES + 1):
                event_queue = asyncio.Queue()
                manager_tool_called = False
                manager_expressed_tool_intent = False
                attempt_agent = (
                    agent
                    if attempt == 0
                    else build_manager_agent(
                        model,
                        on_places_stream,
                        force_places_tool=True,
                    )
                )
                result = Runner.run_streamed(
                    attempt_agent,
                    attempt_input,
                    context=workflow_context,
                    max_turns=MAX_MANAGER_AGENT_TURNS,
                    session=session,
                )

                async def produce_manager_events() -> None:
                    nonlocal manager_expressed_tool_intent, manager_tool_called
                    try:
                        async for stream_event in result.stream_events():
                            if self._is_tool_call_event(stream_event):
                                manager_tool_called = True
                            if self._expresses_places_tool_intent(stream_event):
                                manager_expressed_tool_intent = True
                            converted = self._convert_sdk_event(
                                stream_event,
                                scope="manager",
                                agent_name=attempt_agent.name,
                            )
                            if converted is not None:
                                await event_queue.put(converted)
                    finally:
                        await event_queue.put(None)

                producer_task = asyncio.create_task(produce_manager_events())
                while True:
                    queued_event = await event_queue.get()
                    if queued_event is None:
                        break
                    yield queued_event
                await producer_task

                final_output = AgentAnswer.model_validate(result.final_output)
                should_retry = (
                    attempt < MAX_MANAGER_PROGRESS_RETRIES
                    and self._needs_manager_retry(
                        final_output.answer,
                        manager_tool_called,
                        needs_places_tool=final_output.needs_places_tool,
                        expressed_tool_intent=manager_expressed_tool_intent,
                    )
                )
                if not should_retry:
                    break

                removed_item = await session.pop_item()
                logger.debug("Removed incomplete session item: %s", removed_item)
                yield self._event(
                    "agent_thinking",
                    {
                        "scope": "manager",
                        "agent": agent.name,
                        "thinking": (
                            "The previous response did not execute the required "
                            "Places tool. Retrying with places_agent required."
                        ),
                    },
                )
                attempt_input = (
                    "Your previous response only announced a future action. "
                    "Reconsider the user's preceding request. If live place "
                    "information is needed. The places_agent tool is now "
                    "required: call it with the user's complete request as "
                    "plain input, then synthesize its result."
                )

            if final_output is None:
                raise RuntimeError("Manager completed without a final output")
            yield self._event(
                "agent_completed",
                {"output": final_output.model_dump(mode="json")},
            )
        except asyncio.CancelledError:
            if result is not None:
                result.cancel()
            if producer_task is not None:
                producer_task.cancel()
                with suppress(asyncio.CancelledError):
                    await producer_task
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
                    getattr(raw_item, "arguments", "")
                )
                data = {
                    "scope": scope,
                    "agent": agent_name,
                    "tool": getattr(raw_item, "name", "unknown_tool"),
                    "parameters": parameters,
                }
                if isinstance(parameters, dict) and "input" in parameters:
                    data["input"] = parameters["input"]
                return cls._event("tool_call", data)
            if stream_event.name == "tool_output":
                return cls._event(
                    "tool_output",
                    {
                        "scope": scope,
                        "agent": agent_name,
                        "output": cls._parse_json_value(
                            getattr(raw_item, "output", "")
                        ),
                    },
                )
            if stream_event.name == "message_output_created" and scope != "manager":
                output = cls._message_output(raw_item)
                if output is not None:
                    return cls._event(
                        "agent_output",
                        {
                            "scope": scope,
                            "agent": agent_name,
                            "output": output,
                        },
                    )
        return None

    @classmethod
    def _message_output(cls, raw_item: Any) -> Any | None:
        content = getattr(raw_item, "content", None)
        if not isinstance(content, list):
            return None
        text_parts = [
            str(getattr(part, "text", ""))
            for part in content
            if getattr(part, "text", None)
        ]
        text = "".join(text_parts).strip()
        if not text:
            return None
        output = cls._parse_json_value(text)
        if isinstance(output, dict) and not output.get("answer", True):
            return None
        return output

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
    def _is_tool_call_event(stream_event: Any) -> bool:
        if getattr(stream_event, "type", None) != "run_item_stream_event":
            return False
        if getattr(stream_event, "name", None) == "tool_called":
            return True
        item_type = getattr(getattr(stream_event, "item", None), "type", None)
        return item_type in {"tool_call_item", "tool_call"}

    @staticmethod
    def _expresses_places_tool_intent(stream_event: Any) -> bool:
        if getattr(stream_event, "type", None) != "raw_response_event":
            return False
        data = getattr(stream_event, "data", None)
        event_type = getattr(data, "type", "")
        if event_type != "response.reasoning_text.done":
            return False
        text = str(getattr(data, "text", "")).casefold()
        intent_phrases = ("call", "use", "invoke")
        return "places_agent" in text and any(
            phrase in text for phrase in intent_phrases
        )

    @staticmethod
    def _needs_manager_retry(
        answer: str,
        tool_called: bool,
        needs_places_tool: bool = False,
        expressed_tool_intent: bool = False,
    ) -> bool:
        if tool_called:
            return False
        if needs_places_tool or expressed_tool_intent:
            return True
        normalized = answer.casefold().strip()
        if normalized in {"", "null", "none", "n/a", "..."}:
            return True
        progress_phrases = (
            "calling the",
            "i am calling",
            "i'm calling",
            "i’m calling",
            "i will call",
            "i'll call",
            "i’ll call",
            "should call",
            "need to call",
            "about to call",
            "i will use",
            "i'll use",
            "i’ll use",
            "let me search",
            "i will search",
            "i'll search",
            "searching for",
            "let me check",
            "i will check",
            "i'll check",
        )
        return any(phrase in normalized for phrase in progress_phrases)

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
