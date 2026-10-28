import pytest
from pydantic import ValidationError

from app.agent.models import AgentAnswer, LocationSearchToolResult
from app.models import (
    NearbySearchResponse,
    Place,
    PlaceSearchRequest,
    PriceRange,
)


def test_price_range_is_typed_and_normalized() -> None:
    price_range = PriceRange.model_validate(
        {
            "startPrice": {"currencyCode": "sgd", "units": "10"},
            "endPrice": {"currencyCode": "SGD", "units": "25"},
        }
    )

    assert price_range.start_price.currency_code == "SGD"
    assert price_range.start_price.units == 10
    assert price_range.end_price.units == 25


def test_invalid_region_rating_and_response_counts_are_rejected() -> None:
    with pytest.raises(ValidationError, match="ISO 3166-1"):
        PlaceSearchRequest(query="Paris", region_code="XX")

    with pytest.raises(ValidationError):
        Place(id="bad-rating", rating=5.1)

    with pytest.raises(ValidationError, match="count must equal"):
        NearbySearchResponse(
            center={"latitude": 1.3, "longitude": 103.8},
            radius_meters=1000,
            count=1,
            places=[],
        )

    with pytest.raises(ValidationError, match="match_count must equal"):
        LocationSearchToolResult(
            query="Singapore",
            region_code="SG",
            match_count=1,
            matches=[],
        )


def test_agent_answer_rejects_broken_google_maps_markdown() -> None:
    with pytest.raises(ValidationError, match="Google Maps label"):
        AgentAnswer(
            answer=(
                "[View on Google Maps]\\([https://www.google.com/maps/search/)"
            )
        )

    answer = AgentAnswer(
        answer=(
            "[View on Google Maps](https://www.google.com/maps/search/"
            "?api=1&query=Library&query_place_id=place-1)"
        )
    )
    assert answer.answer.startswith("[View on Google Maps]")
