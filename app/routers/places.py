from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import get_google_places_service
from app.models import (
    NearbySearchRequest,
    NearbySearchResponse,
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
