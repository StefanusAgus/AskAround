from typing import Any, Dict

import httpx

from app.constants import GOOGLE_PLACES_BASE_URL, SEARCH_FIELD_MASK
from app.models import (
    Coordinates,
    NearbySearchRequest,
    NearbySearchResponse,
    Place,
    PlaceSearchRequest,
    PlaceSearchResponse,
)


class GooglePlacesError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class GooglePlacesService:
    def __init__(self, api_key: str, http_client: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._http_client = http_client

    async def search(self, request: PlaceSearchRequest) -> PlaceSearchResponse:
        payload: Dict[str, Any] = {
            "textQuery": request.query,
            "pageSize": request.max_results,
        }
        payload["languageCode"] = request.language_code
        payload["regionCode"] = request.region_code.upper()

        data = await self._request(
            "POST",
            "/places:searchText",
            field_mask=SEARCH_FIELD_MASK,
            json=payload,
        )
        places = [Place.model_validate(place) for place in data.get("places", [])]
        return PlaceSearchResponse(
            query=request.query,
            count=len(places),
            places=places,
        )

    async def search_nearby(
        self, request: NearbySearchRequest
    ) -> NearbySearchResponse:
        payload: Dict[str, Any] = {
            "maxResultCount": request.max_results,
            "rankPreference": request.rank_preference.value,
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": request.latitude,
                        "longitude": request.longitude,
                    },
                    "radius": request.radius_meters,
                }
            },
        }
        if request.included_types:
            payload["includedTypes"] = request.included_types
        payload["languageCode"] = request.language_code
        payload["regionCode"] = request.region_code.upper()

        data = await self._request(
            "POST",
            "/places:searchNearby",
            field_mask=SEARCH_FIELD_MASK,
            json=payload,
        )
        places = [Place.model_validate(place) for place in data.get("places", [])]
        return NearbySearchResponse(
            center=Coordinates(
                latitude=request.latitude,
                longitude=request.longitude,
            ),
            radius_meters=request.radius_meters,
            count=len(places),
            places=places,
        )

    async def _request(
        self,
        method: str,
        path: str,
        field_mask: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        try:
            response = await self._http_client.request(
                method,
                f"{GOOGLE_PLACES_BASE_URL}{path}",
                headers={
                    "X-Goog-Api-Key": self._api_key,
                    "X-Goog-FieldMask": field_mask,
                },
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            message = self._google_error_message(exc.response)
            raise GooglePlacesError(
                f"Google Places API returned {exc.response.status_code}: {message}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise GooglePlacesError(
                f"Could not reach Google Places API: {exc}"
            ) from exc
        except ValueError as exc:
            raise GooglePlacesError(
                "Google Places API returned an invalid JSON response."
            ) from exc

    @staticmethod
    def _google_error_message(response: httpx.Response) -> str:
        try:
            error = response.json().get("error", {})
            return error.get("message", response.text)
        except ValueError:
            return response.text or "Unknown upstream error"
