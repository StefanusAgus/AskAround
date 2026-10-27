from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field


class AgentModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class AgentChatRequest(AgentModel):
    message: str = Field(
        min_length=1,
        max_length=10_000,
        description="The user's message to the agent.",
        examples=["What can you help me with?"],
    )


class AgentAnswer(AgentModel):
    answer: str = Field(description="The agent's response to the user.")


class AgentStreamEvent(AgentModel):
    event: str
    data: Dict[str, Any]
