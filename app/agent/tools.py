import logging
from urllib.parse import urlencode

from agents import RunContextWrapper, function_tool

from app.agent.context import AgentContext
from app.agent.models import (
    LocationSearchToolResult,
    NearbySearchToolResult,
    PlaceCandidate,
)
from app.constants import (
    DEFAULT_REGION_CODE,
    LOCATION_SEARCH_MAX_RESULTS,
    MAX_AGENT_TOOL_CALLS,
    NEARBY_SEARCH_DEFAULT_RADIUS_METERS,
    NEARBY_SEARCH_MAX_RESULTS,
)
from app.models import NearbySearchRequest, Place, PlaceSearchRequest

logger = logging.getLogger(__name__)


class ToolCallLimitExceeded(RuntimeError):
    """Raised when the specialist exceeds the Google API call budget."""


def _reserve_google_api_call(context: AgentContext, tool_name: str) -> int:
    if context.google_places_tool_calls >= MAX_AGENT_TOOL_CALLS:
        message = (
            "Google Places tool-call limit reached: "
            f"{MAX_AGENT_TOOL_CALLS} calls per user turn."
        )
        logger.error("%s Attempted tool: %s", message, tool_name)
        raise ToolCallLimitExceeded(message)

    context.google_places_tool_calls += 1
    return context.google_places_tool_calls


def _normalize_region_code(region_code: str) -> str:
    normalized = _clean_tool_string(region_code).upper()
    if len(normalized) != 2 or not normalized.isalpha():
        logger.warning(
            "Invalid tool region_code=%r; defaulting to %s",
            region_code,
            DEFAULT_REGION_CODE,
        )
        return DEFAULT_REGION_CODE
    return normalized


def _clean_tool_string(value: str) -> str:
    return value.strip().strip("\\\"'").strip()


def _build_google_maps_url(place: Place) -> str:
    query = (
        place.display_name.text
        if place.display_name
        else place.formatted_address or place.id
    )
    parameters = urlencode(
        {
            "api": "1",
            "query": query,
            "query_place_id": place.id,
        }
    )
    return f"https://www.google.com/maps/search/?{parameters}"


def _to_place_candidate(place: Place) -> PlaceCandidate:
    return PlaceCandidate(
        place_id=place.id,
        name=place.display_name.text if place.display_name else None,
        formatted_address=place.formatted_address,
        latitude=place.location.latitude if place.location else None,
        longitude=place.location.longitude if place.location else None,
        primary_type=place.primary_type,
        types=place.types,
        rating=place.rating,
        user_rating_count=place.user_rating_count,
        google_maps_uri=_build_google_maps_url(place),
        national_phone_number=place.national_phone_number,
        website_uri=place.website_uri,
        current_opening_hours=place.current_opening_hours,
        regular_opening_hours=place.regular_opening_hours,
        open_now=(
            place.current_opening_hours.open_now
            if place.current_opening_hours
            else place.regular_opening_hours.open_now
            if place.regular_opening_hours
            else None
        ),
        price_level=place.price_level,
        price_range=place.price_range,
    )


def _rank_places(places: list[Place]) -> list[Place]:
    """Put highly rated, well-reviewed places first without dropping results."""
    return sorted(
        places,
        key=lambda place: (
            place.rating is not None,
            place.rating or 0,
            place.user_rating_count or 0,
        ),
        reverse=True,
    )


async def execute_location_search(
    context: RunContextWrapper[AgentContext], query: str, region_code: str
) -> LocationSearchToolResult:
    """Resolve a postcode, address, district, landmark, or named place."""
    _reserve_google_api_call(
        context.context,
        "search_google_places_text",
    )

    try:
        query = _clean_tool_string(query)
        context.context.region_code = _normalize_region_code(region_code)
        response = await context.context.google_places.search(
            PlaceSearchRequest(
                query=query,
                max_results=LOCATION_SEARCH_MAX_RESULTS,
                region_code=context.context.region_code,
            )
        )
        result = LocationSearchToolResult(
            query=query,
            region_code=context.context.region_code,
            match_count=response.count,
            matches=[_to_place_candidate(place) for place in response.places],
        )
        return result
    except Exception:
        logger.exception(
            "Text Search failed for query=%r region_code=%r",
            query,
            region_code,
        )
        raise


async def execute_nearby_search(
    context: RunContextWrapper[AgentContext],
    latitude: float,
    longitude: float,
    included_types: list[str],
    region_code: str,
    radius_meters: float = NEARBY_SEARCH_DEFAULT_RADIUS_METERS,
) -> NearbySearchToolResult:
    """Find points of interest around coordinates using Google place types."""
    _reserve_google_api_call(
        context.context,
        "search_google_places_nearby",
    )

    try:
        context.context.region_code = _normalize_region_code(region_code)
        included_types = [
            _clean_tool_string(place_type).lower()
            for place_type in included_types
        ]
        request = NearbySearchRequest(
            latitude=latitude,
            longitude=longitude,
            radius_meters=radius_meters,
            included_types=included_types,
            max_results=NEARBY_SEARCH_MAX_RESULTS,
            region_code=context.context.region_code,
        )
        response = await context.context.google_places.search_nearby(request)
        result = NearbySearchToolResult(
            region_code=context.context.region_code,
            latitude=response.center.latitude,
            longitude=response.center.longitude,
            radius_meters=response.radius_meters,
            match_count=response.count,
            matches=[
                _to_place_candidate(place)
                for place in _rank_places(response.places)
            ],
        )
        return result
    except Exception:
        logger.exception(
            "Nearby Search failed for latitude=%s longitude=%s "
            "included_types=%s region_code=%r radius_meters=%s",
            latitude,
            longitude,
            included_types,
            region_code,
            radius_meters,
        )
        raise


search_google_places_text = function_tool(
    execute_location_search,
    name_override="search_google_places_text",
    description_override=(
        "Resolve a postcode, address, district, landmark, or named place. "
        "Returns candidates with coordinates for subsequent nearby searches."
    ),
)

search_google_places_nearby = function_tool(
    execute_nearby_search,
    name_override="search_google_places_nearby",
    description_override=(
        "Find points of interest around coordinates. included_types must use "
        "Google place types such as sushi_restaurant, ramen_restaurant, or library."
    ),
)

