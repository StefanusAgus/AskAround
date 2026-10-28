from collections.abc import Awaitable, Callable
from typing import Any

from agents import Agent, Model, ModelSettings

from app.agent.models import AgentAnswer, PlacesAgentOutput
from app.agent.prompts import MANAGER_AGENT_INSTRUCTIONS, PLACES_AGENT_INSTRUCTIONS
from app.agent.tools import search_google_places_nearby, search_google_places_text
from app.constants import MAX_PLACES_AGENT_TURNS

NestedStreamHandler = Callable[[dict[str, Any]], Awaitable[None]]


def build_manager_agent(
    model: Model,
    on_places_stream: NestedStreamHandler,
    force_places_tool: bool = False,
) -> Agent:
    places_agent = Agent(
        name="Places Specialist",
        instructions=PLACES_AGENT_INSTRUCTIONS,
        model=model,
        model_settings=ModelSettings(tool_choice="required"),
        reset_tool_choice=True,
        tools=[
            search_google_places_text,
            search_google_places_nearby,
        ],
        output_type=PlacesAgentOutput,
    )
    places_agent_tool = places_agent.as_tool(
        tool_name="places_agent",
        tool_description=(
            "Handle live Google Places resolution, nearby recommendations, "
            "and the Text Search to Nearby Search sequence. Pass the complete "
            "user request as plain input."
        ),
        max_turns=MAX_PLACES_AGENT_TURNS,
        on_stream=on_places_stream,
        failure_error_function=None,
    )

    return Agent(
        name="AskAround Manager",
        instructions=MANAGER_AGENT_INSTRUCTIONS,
        model=model,
        model_settings=(
            ModelSettings(tool_choice="places_agent")
            if force_places_tool
            else ModelSettings()
        ),
        tools=[places_agent_tool],
        output_type=AgentAnswer,
    )
