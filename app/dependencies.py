from fastapi import Request

from app.config import Settings
from app.services.google_places import GooglePlacesService


def get_google_places_service(request: Request) -> GooglePlacesService:
    settings = Settings.from_environment()
    return GooglePlacesService(
        api_key=settings.google_maps_api_key,
        http_client=request.app.state.http_client,
    )
