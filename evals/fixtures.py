from typing import Any

from app.models import (
    Coordinates,
    NearbySearchRequest,
    NearbySearchResponse,
    PlaceSearchRequest,
    PlaceSearchResponse,
)
from evals.models import EvalCase, ToolCallRecord


class FixtureGooglePlacesService:
    """In-memory Google Places replacement scoped to one evaluation case."""

    def __init__(self, case: EvalCase) -> None:
        self.case = case
        self.tool_calls: list[ToolCallRecord] = []

    async def search(self, request: PlaceSearchRequest) -> PlaceSearchResponse:
        self.tool_calls.append(
            ToolCallRecord(
                tool="search_google_places_text",
                parameters=request.model_dump(mode="json"),
            )
        )
        return PlaceSearchResponse(
            query=request.query,
            count=len(self.case.text_results),
            places=self.case.text_results,
        )

    async def search_nearby(
        self,
        request: NearbySearchRequest,
    ) -> NearbySearchResponse:
        self.tool_calls.append(
            ToolCallRecord(
                tool="search_google_places_nearby",
                parameters=request.model_dump(mode="json"),
            )
        )
        requested_types = request.included_types
        places = []
        for place_type in requested_types:
            places.extend(self.case.nearby_results.get(place_type, []))

        unique_places = list({place.id: place for place in places}.values())
        return NearbySearchResponse(
            center=Coordinates(
                latitude=request.latitude,
                longitude=request.longitude,
            ),
            radius_meters=request.radius_meters,
            count=len(unique_places),
            places=unique_places,
        )

    async def get_details(self, *_: Any, **__: Any) -> None:
        raise AssertionError("Place Details is outside this evaluation scope")
