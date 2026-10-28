from dataclasses import dataclass

from app.constants import DEFAULT_REGION_CODE
from app.services.google_places import GooglePlacesService


@dataclass
class AgentContext:
    google_places: GooglePlacesService
    region_code: str = DEFAULT_REGION_CODE
    google_places_tool_calls: int = 0
