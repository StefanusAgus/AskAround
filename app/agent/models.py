from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.models import OpeningHours


class AgentModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class AgentChatRequest(AgentModel):
    message: str = Field(
        min_length=1,
        max_length=10_000,
        description="The user's message to the agent.",
        examples=["What can you help me with?"],
    )
    session_id: str = Field(
        default_factory=lambda: uuid4().hex,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Conversation ID. Reuse it for follow-up messages.",
    )


class AgentAnswer(AgentModel):
    answer: str = Field(
        description=(
            "The agent's user-facing response in safe Markdown, including "
            "ranked place names and Google Maps links when available."
        )
    )


class PlaceCandidate(AgentModel):
    place_id: str
    name: Optional[str] = None
    formatted_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    primary_type: Optional[str] = None
    types: List[str] = Field(default_factory=list)
    rating: Optional[float] = None
    user_rating_count: Optional[int] = None
    google_maps_uri: Optional[str] = None
    national_phone_number: Optional[str] = None
    website_uri: Optional[str] = None
    current_opening_hours: Optional[OpeningHours] = None
    regular_opening_hours: Optional[OpeningHours] = None
    open_now: Optional[bool] = None
    price_level: Optional[str] = None
    price_range: Optional[Any] = None


class LocationSearchToolResult(AgentModel):
    query: str
    region_code: str
    match_count: int
    matches: List[PlaceCandidate]


class NearbySearchToolResult(AgentModel):
    region_code: str
    latitude: float
    longitude: float
    radius_meters: float
    match_count: int
    matches: List[PlaceCandidate]


class AgentStreamEvent(AgentModel):
    event: str
    data: Dict[str, Any]
