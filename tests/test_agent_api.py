from dataclasses import dataclass
from threading import RLock
from typing import Any, AsyncIterator

import pytest
from fastapi.testclient import TestClient

from app.agent.models import AgentStreamEvent
from app.agent.service import AgentService
from app.config import OpenRouterSettings
from app.main import app
from app.routers.agent import get_agent_service


class FakeAgentService:
    async def stream(
        self, message: str, session_id: str
    ) -> AsyncIterator[AgentStreamEvent]:
        yield AgentStreamEvent(
            event="agent_started",
            data={
                "agent": "AskAround Assistant",
                "input": message,
                "session_id": session_id,
            },
        )
        yield AgentStreamEvent(
            event="agent_completed",
            data={"output": {"answer": "Hello from the test agent."}},
        )


@dataclass
class FakeAgent:
    name: str
    lock: Any


@dataclass
class FakeRunItem:
    agent: FakeAgent
    raw_item: dict[str, str]
    type: str = "message_output_item"


def test_run_item_serialization_does_not_copy_agent_lock() -> None:
    item = FakeRunItem(
        agent=FakeAgent(name="AskAround Assistant", lock=RLock()),
        raw_item={"type": "message", "text": "Hello"},
    )

    serialized = AgentService._run_item_data(item)

    assert serialized == {
        "type": "message_output_item",
        "agent": "AskAround Assistant",
        "raw_item": {"type": "message", "text": "Hello"},
    }


def test_delta_events_are_excluded_from_agent_trace() -> None:
    assert AgentService._is_delta_event("response.output_text.delta") is True
    assert AgentService._is_delta_event("response.reasoning_text.delta") is True
    assert AgentService._is_delta_event("response.output_text.done") is False
    assert AgentService._is_delta_event("response.completed") is False


@pytest.mark.asyncio
async def test_agent_service_starts_without_calling_openrouter() -> None:
    service = AgentService(
        OpenRouterSettings(api_key="test-key", model="openai/gpt-4.1-mini")
    )
    stream = service.stream("Hello", "test-session")

    event = await anext(stream)
    await stream.aclose()

    assert event.event == "agent_started"
    assert event.data["model"] == "openai/gpt-4.1-mini"
    assert event.data["session_id"] == "test-session"


def test_agent_chat_streams_server_sent_events() -> None:
    app.dependency_overrides[get_agent_service] = FakeAgentService
    try:
        with TestClient(app) as client:
            response = client.post(
                "/agent/chat",
                json={"message": "Hello", "session_id": "chat-session"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: agent_started" in response.text
    assert '"input": "Hello"' in response.text
    assert '"session_id": "chat-session"' in response.text
    assert "event: agent_completed" in response.text
    assert '"answer": "Hello from the test agent."' in response.text
