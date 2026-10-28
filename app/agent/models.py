import re
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import OpeningHours, PriceLevel, PriceRange


GOOGLE_MAPS_LINK_LABEL = "[View on Google Maps]"
GOOGLE_MAPS_LINK_PATTERN = re.compile(
    r"\[View on Google Maps\]\(https://www\.google\.com/maps/[^\s)]+\)"
)


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
        min_length=1,
        max_length=50_000,
        description=(
            "The agent's user-facing response in safe Markdown, including "
            "ranked place names and Google Maps links when available."
        )
    )

    @field_validator("answer")
    @classmethod
    def validate_answer_markdown(cls, value: str) -> str:
        answer = value.strip()
        label_count = answer.count(GOOGLE_MAPS_LINK_LABEL)
        valid_link_count = len(GOOGLE_MAPS_LINK_PATTERN.findall(answer))
        if label_count != valid_link_count:
            raise ValueError(
                "Every Google Maps label must contain one valid, single-line "
                "https://www.google.com/maps/ Markdown link"
            )
        return answer


class PlaceCandidate(AgentModel):
    place_id: str
    name: Optional[str] = None
    formatted_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    primary_type: Optional[str] = None
    types: List[str] = Field(default_factory=list)
    rating: Optional[float] = Field(default=None, ge=0, le=5)
    user_rating_count: Optional[int] = Field(default=None, ge=0)
    google_maps_uri: Optional[str] = None
    national_phone_number: Optional[str] = None
    website_uri: Optional[str] = None
    current_opening_hours: Optional[OpeningHours] = None
    regular_opening_hours: Optional[OpeningHours] = None
    open_now: Optional[bool] = None
    price_level: Optional[PriceLevel] = None
    price_range: Optional[PriceRange] = None


class LocationSearchToolResult(AgentModel):
    query: str
    region_code: str
    match_count: int
    matches: List[PlaceCandidate]

    @model_validator(mode="after")
    def validate_match_count(self) -> "LocationSearchToolResult":
        if self.match_count != len(self.matches):
            raise ValueError("match_count must equal the number of matches")
        return self


class NearbySearchToolResult(AgentModel):
    region_code: str
    latitude: float
    longitude: float
    radius_meters: float
    match_count: int
    matches: List[PlaceCandidate]

    @model_validator(mode="after")
    def validate_match_count(self) -> "NearbySearchToolResult":
        if self.match_count != len(self.matches):
            raise ValueError("match_count must equal the number of matches")
        return self


class AgentStreamEvent(AgentModel):
    event: str
    data: Dict[str, Any]
