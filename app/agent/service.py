import asyncio
import json
import logging
from dataclasses import fields, is_dataclass
from typing import Any, AsyncIterator

from agents import Agent, OpenAIChatCompletionsModel, Runner, set_tracing_disabled
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.agent.models import AgentAnswer, AgentStreamEvent
from app.agent.prompts import NEARBY_ASSISTANT_INSTRUCTIONS
from app.config import OpenRouterSettings
from app.constants import OPENROUTER_BASE_URL

logger = logging.getLogger(__name__)

# OpenAI tracing requires a separate OpenAI API key. This application uses
# OpenRouter only, so traces stay local in stdout for now.
set_tracing_disabled(True)


class AgentService:
    def __init__(self, settings: OpenRouterSettings) -> None:
        self._settings = settings

    async def stream(self, message: str) -> AsyncIterator[AgentStreamEvent]:
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
            agent = Agent(
                name="AskAround Assistant",
                instructions=NEARBY_ASSISTANT_INSTRUCTIONS,
                model=model,
                output_type=AgentAnswer,
            )

            yield self._event(
                "agent_started",
                {
                    "agent": agent.name,
                    "model": self._settings.model,
                    "input": message,
                },
            )

            result = Runner.run_streamed(agent, message, max_turns=1)
            async for stream_event in result.stream_events():
                if stream_event.type == "raw_response_event":
                    yield self._event(
                        "raw_response_event",
                        {
                            "type": getattr(
                                stream_event.data,
                                "type",
                                type(stream_event.data).__name__,
                            ),
                            "data": self._jsonable(stream_event.data),
                        },
                    )
                elif stream_event.type == "run_item_stream_event":
                    yield self._event(
                        "agent_step",
                        {
                            "name": stream_event.name,
                            "item": self._run_item_data(stream_event.item),
                        },
                    )
                elif stream_event.type == "agent_updated_stream_event":
                    yield self._event(
                        "agent_updated",
                        {"agent": stream_event.new_agent.name},
                    )

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
            await client.close()

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
    def _event(event: str, data: dict[str, Any]) -> AgentStreamEvent:
        stream_event = AgentStreamEvent(event=event, data=data)
        logger.info(
            "Agent event: %s",
            json.dumps(stream_event.model_dump(mode="json"), ensure_ascii=False),
        )
        return stream_event
