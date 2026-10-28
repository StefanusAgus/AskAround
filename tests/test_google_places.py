import json

import httpx
import pytest

from app.models import NearbySearchRequest, PlaceSearchRequest, RankPreference
from app.services.google_places import GooglePlacesError, GooglePlacesService


@pytest.mark.asyncio
async def test_search_returns_ranked_candidates() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/places:searchText"
        assert request.headers["X-Goog-Api-Key"] == "test-key"
        assert request.headers["X-Goog-FieldMask"].startswith("places.id")
        assert json.loads(request.content) == {
            "textQuery": "018956 Singapore",
            "pageSize": 3,
            "languageCode": "en",
            "regionCode": "SG",
        }
        return httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "place-1",
                        "displayName": {"text": "Marina Bay Sands"},
                        "formattedAddress": "10 Bayfront Avenue, Singapore",
                        "location": {"latitude": 1.2834, "longitude": 103.8607},
                    },
                    {
                        "id": "place-2",
                        "displayName": {"text": "Marina Bay"},
                    },
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GooglePlacesService("test-key", client)
        result = await service.search(
            PlaceSearchRequest(query="018956 Singapore", max_results=3)
        )

    assert result.count == 2
    assert result.places[0].display_name.text == "Marina Bay Sands"
    assert result.places[0].location.latitude == 1.2834


@pytest.mark.asyncio
async def test_nearby_search_sends_location_and_filters() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/places:searchNearby"
        payload = json.loads(request.content)
        assert payload == {
            "maxResultCount": 4,
            "rankPreference": "DISTANCE",
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": 1.2834, "longitude": 103.8607},
                    "radius": 750.0,
                }
            },
            "includedTypes": ["restaurant", "cafe"],
            "languageCode": "en",
            "regionCode": "SG",
        }
        return httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "nearby-place",
                        "displayName": {"text": "Nearby Restaurant"},
                    }
                ]
            },
        )

    request = NearbySearchRequest(
        latitude=1.2834,
        longitude=103.8607,
        radius_meters=750,
        included_types=["restaurant", "cafe"],
        max_results=4,
        rank_preference=RankPreference.distance,
        region_code="sg",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GooglePlacesService("test-key", client)
        result = await service.search_nearby(request)

    assert result.count == 1
    assert result.center.latitude == 1.2834
    assert result.places[0].id == "nearby-place"


def test_nearby_search_rejects_response_only_place_type() -> None:
    with pytest.raises(ValueError, match="point_of_interest"):
        NearbySearchRequest(
            latitude=1.2834,
            longitude=103.8607,
            included_types=["point_of_interest"],
        )


@pytest.mark.asyncio
async def test_google_error_is_exposed_clearly() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            request=request,
            json={"error": {"message": "API key is not authorized"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = GooglePlacesService("bad-key", client)
        with pytest.raises(GooglePlacesError, match="API key is not authorized"):
            await service.search(PlaceSearchRequest(query="Singapore"))
