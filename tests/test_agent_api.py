from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from types import SimpleNamespace
from typing import Any, AsyncIterator

import pytest
from agents import OpenAIChatCompletionsModel, RunContextWrapper
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from app.agent.context import AgentContext
from app.agent.models import AgentStreamEvent
from app.agent.prompts import build_askaround_agent_instructions
from app.agent.service import AgentService
from app.agent.tools import (
    ToolCallLimitExceeded,
    _rank_places,
    execute_location_search,
    execute_nearby_search,
)
from app.agent.workflow import build_agent
from app.config import OpenRouterSettings
from app.constants import MAX_AGENT_TOOL_CALLS
from app.main import app
from app.models import (
    Coordinates,
    DisplayName,
    NearbySearchResponse,
    OpeningHours,
    Place,
    PlaceSearchResponse,
)
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


class FakeGooglePlacesService:
    def __init__(self) -> None:
        self.requests = []

    async def search(self, request: Any) -> PlaceSearchResponse:
        self.requests.append(request)
        return PlaceSearchResponse(
            query=request.query,
            count=1,
            places=[
                Place(
                    id="test-place-id",
                    display_name=DisplayName(text="Geylang Serai"),
                    formatted_address="Geylang Serai, Singapore",
                    location=Coordinates(latitude=1.3167, longitude=103.8982),
                    primary_type="neighborhood",
                    types=["neighborhood", "political"],
                )
            ],
        )

    async def search_nearby(self, request: Any) -> NearbySearchResponse:
        self.requests.append(request)
        return NearbySearchResponse(
            center=Coordinates(
                latitude=request.latitude,
                longitude=request.longitude,
            ),
            radius_meters=request.radius_meters,
            count=1,
            places=[
                Place(
                    id="ramen-place-id",
                    display_name=DisplayName(text="Test Ramen"),
                    formatted_address="1 Ramen Road, Singapore",
                    location=Coordinates(latitude=1.32, longitude=103.89),
                    primary_type="ramen_restaurant",
                    types=["ramen_restaurant", "restaurant"],
                    rating=4.5,
                    user_rating_count=120,
                    google_maps_uri="https://maps.google.com/?cid=test",
                    regular_opening_hours=OpeningHours(
                        open_now=True,
                        weekday_descriptions=[
                            "Wednesday: 11:00 AM - 10:00 PM"
                        ],
                    ),
                    price_level="PRICE_LEVEL_MODERATE",
                    price_range={
                        "startPrice": {"currencyCode": "SGD", "units": "15"},
                        "endPrice": {"currencyCode": "SGD", "units": "30"},
                    },
                )
            ],
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


def test_sdk_events_are_reduced_to_focused_trace_events() -> None:
    lifecycle_event = SimpleNamespace(
        type="raw_response_event",
        data=SimpleNamespace(type="response.created"),
    )
    reasoning_event = SimpleNamespace(
        type="raw_response_event",
        data=SimpleNamespace(
            type="response.reasoning_text.done",
            text="Resolve the postcode before searching nearby.",
        ),
    )
    tool_event = SimpleNamespace(
        type="run_item_stream_event",
        name="tool_called",
        item=SimpleNamespace(
            raw_item=SimpleNamespace(
                name="search_google_places_text",
                arguments='{"query":"398371","region_code":"SG"}',
            )
        ),
    )
    tool_output_event = SimpleNamespace(
        type="run_item_stream_event",
        name="tool_output",
        item=SimpleNamespace(
            raw_item={"output": '{"match_count":1,"matches":[]}'},
        ),
    )

    assert AgentService._convert_sdk_event(
        lifecycle_event, "manager", "AskAround Manager"
    ) is None
    reasoning = AgentService._convert_sdk_event(
        reasoning_event, "agent", "AskAround"
    )
    tool_call = AgentService._convert_sdk_event(
        tool_event, "agent", "AskAround"
    )
    tool_output = AgentService._convert_sdk_event(
        tool_output_event, "agent", "AskAround"
    )

    assert reasoning.event == "agent_thinking"
    assert reasoning.data["thinking"] == (
        "Resolve the postcode before searching nearby."
    )
    assert tool_call.event == "tool_call"
    assert tool_call.data["tool"] == "search_google_places_text"
    assert tool_call.data["parameters"] == {
        "query": "398371",
        "region_code": "SG",
    }
    assert tool_output.event == "tool_output"
    assert tool_output.data["output"] == {"match_count": 1, "matches": []}


@pytest.mark.asyncio
async def test_single_agent_has_both_google_tools() -> None:
    client = AsyncOpenAI(api_key="test-key")
    model = OpenAIChatCompletionsModel(model="test-model", openai_client=client)

    try:
        agent = build_agent(model)
    finally:
        await client.close()

    assert agent.name == "AskAround"
    assert agent.model_settings.tool_choice == "auto"
    assert agent.reset_tool_choice is True
    assert [tool.name for tool in agent.tools] == [
        "search_google_places_text",
        "search_google_places_nearby",
    ]


@pytest.mark.asyncio
async def test_agent_service_starts_without_calling_openrouter() -> None:
    service = AgentService(
        OpenRouterSettings(api_key="test-key", model="openai/gpt-4.1-mini"),
        FakeGooglePlacesService(),
    )
    stream = service.stream("Hello", "test-session")

    event = await anext(stream)
    await stream.aclose()

    assert event.event == "agent_started"
    assert event.data["model"] == "openai/gpt-4.1-mini"
    assert event.data["session_id"] == "test-session"


@pytest.mark.asyncio
async def test_location_search_tool_returns_structured_google_results() -> None:
    google_places = FakeGooglePlacesService()
    context = RunContextWrapper(
        context=AgentContext(google_places=google_places)
    )

    result = await execute_location_search(context, "Geylang Serai", "SG")

    assert result.query == "Geylang Serai"
    assert result.region_code == "SG"
    assert result.match_count == 1
    assert result.matches[0].place_id == "test-place-id"
    assert result.matches[0].name == "Geylang Serai"
    assert google_places.requests[0].max_results == 5
    assert google_places.requests[0].language_code == "en"
    assert google_places.requests[0].region_code == "SG"


@pytest.mark.asyncio
async def test_location_search_changes_context_for_explicit_region() -> None:
    google_places = FakeGooglePlacesService()
    context = RunContextWrapper(
        context=AgentContext(google_places=google_places)
    )

    result = await execute_location_search(context, "Paris", "fr")

    assert result.region_code == "FR"
    assert context.context.region_code == "FR"
    assert google_places.requests[0].region_code == "FR"
    assert google_places.requests[0].language_code == "en"


@pytest.mark.asyncio
async def test_google_tool_sanitizes_escaped_model_arguments() -> None:
    google_places = FakeGooglePlacesService()
    context = RunContextWrapper(
        context=AgentContext(google_places=google_places)
    )

    result = await execute_location_search(context, '\\"398371\\"', '\\"')

    assert result.query == "398371"
    assert result.region_code == "SG"
    assert google_places.requests[0].query == "398371"
    assert google_places.requests[0].region_code == "SG"


@pytest.mark.asyncio
async def test_location_search_tool_enforces_hard_call_limit() -> None:
    google_places = FakeGooglePlacesService()
    context = RunContextWrapper(
        context=AgentContext(google_places=google_places)
    )

    for _ in range(MAX_AGENT_TOOL_CALLS):
        await execute_location_search(context, "Geylang Serai", "SG")

    with pytest.raises(ToolCallLimitExceeded, match="tool-call limit reached"):
        await execute_location_search(context, "Geylang Serai", "SG")

    assert len(google_places.requests) == MAX_AGENT_TOOL_CALLS


@pytest.mark.asyncio
async def test_nearby_tool_returns_structured_results() -> None:
    google_places = FakeGooglePlacesService()
    context = RunContextWrapper(
        context=AgentContext(google_places=google_places)
    )

    nearby = await execute_nearby_search(
        context,
        latitude=1.3167,
        longitude=103.8982,
        included_types=["ramen_restaurant"],
        region_code="SG",
    )
    assert nearby.matches[0].name == "Test Ramen"
    assert nearby.matches[0].rating == 4.5
    assert nearby.matches[0].user_rating_count == 120
    assert nearby.matches[0].google_maps_uri == "https://maps.google.com/?cid=test"
    assert nearby.matches[0].open_now is True
    assert nearby.matches[0].regular_opening_hours.weekday_descriptions == [
        "Wednesday: 11:00 AM - 10:00 PM"
    ]
    assert nearby.matches[0].price_level == "PRICE_LEVEL_MODERATE"
    assert nearby.matches[0].price_range["startPrice"]["units"] == "15"


def test_agent_prompt_includes_current_time_and_response_requirements() -> None:
    instructions = build_askaround_agent_instructions(
        datetime(2026, 10, 28, 3, 30, tzinfo=timezone.utc)
    )

    assert "Wednesday, 28 October 2026 at 11:30" in instructions
    assert "treat the request as being for today" in instructions
    assert "top\n  3 recommendations" in instructions
    assert "price range" in instructions
    assert "today's matching weekday entry" in instructions
    assert "[View on Google Maps](URL)" in instructions


def test_nearby_results_are_ranked_by_rating_then_review_count() -> None:
    places = [
        Place(id="lower", rating=4.2, user_rating_count=900),
        Place(id="fewer-reviews", rating=4.8, user_rating_count=20),
        Place(id="more-reviews", rating=4.8, user_rating_count=200),
        Place(id="no-rating"),
    ]

    assert [place.id for place in _rank_places(places)] == [
        "more-reviews",
        "fewer-reviews",
        "lower",
        "no-rating",
    ]


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
