from agents import Agent, Model, ModelSettings

from app.agent.models import AgentAnswer
from app.agent.prompts import ASKAROUND_AGENT_INSTRUCTIONS
from app.agent.tools import search_google_places_nearby, search_google_places_text


def build_agent(model: Model) -> Agent:
    return Agent(
        name="AskAround",
        instructions=ASKAROUND_AGENT_INSTRUCTIONS,
        model=model,
        model_settings=ModelSettings(tool_choice="auto"),
        tools=[
            search_google_places_text,
            search_google_places_nearby,
        ],
        output_type=AgentAnswer,
    )
