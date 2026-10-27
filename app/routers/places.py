from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.constants import DEFAULT_LANGUAGE_CODE, DEFAULT_REGION_CODE
from app.dependencies import get_google_places_service
from app.models import (
    NearbySearchRequest,
    NearbySearchResponse,
    Place,
    PlaceSearchRequest,
    PlaceSearchResponse,
)
from app.services.google_places import GooglePlacesService

router = APIRouter(prefix="/places", tags=["places"])


@router.post("/search", response_model=PlaceSearchResponse)
async def search_places(
    request: PlaceSearchRequest,
    service: Annotated[GooglePlacesService, Depends(get_google_places_service)],
) -> PlaceSearchResponse:
    return await service.search(request)


@router.post("/nearby", response_model=NearbySearchResponse)
async def search_nearby_places(
    request: NearbySearchRequest,
    service: Annotated[GooglePlacesService, Depends(get_google_places_service)],
) -> NearbySearchResponse:
    return await service.search_nearby(request)


@router.get("/{place_id}", response_model=Place)
async def get_place_details(
    service: Annotated[GooglePlacesService, Depends(get_google_places_service)],
    place_id: str = Path(min_length=1, description="Google Maps place ID"),
    language_code: str = Query(
        default=DEFAULT_LANGUAGE_CODE,
        description="BCP-47 response language. Defaults to English.",
    ),
    region_code: str = Query(
        default=DEFAULT_REGION_CODE,
        min_length=2,
        max_length=2,
        description="Two-letter result region. Defaults to Singapore (SG).",
    ),
) -> Place:
    return await service.get_details(place_id, language_code, region_code)
