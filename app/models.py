from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.constants import (
    DEFAULT_LANGUAGE_CODE,
    DEFAULT_REGION_CODE,
    GOOGLE_PLACE_FILTER_TYPES,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class DisplayName(ApiModel):
    text: str
    language_code: Optional[str] = Field(default=None, alias="languageCode")


class Coordinates(ApiModel):
    latitude: float
    longitude: float


class OpeningHours(ApiModel):
    open_now: Optional[bool] = Field(default=None, alias="openNow")
    weekday_descriptions: List[str] = Field(
        default_factory=list, alias="weekdayDescriptions"
    )


class Place(ApiModel):
    id: str
    display_name: Optional[DisplayName] = Field(default=None, alias="displayName")
    formatted_address: Optional[str] = Field(default=None, alias="formattedAddress")
    location: Optional[Coordinates] = None
    types: List[str] = Field(default_factory=list)
    primary_type: Optional[str] = Field(default=None, alias="primaryType")
    business_status: Optional[str] = Field(default=None, alias="businessStatus")
    google_maps_uri: Optional[str] = Field(default=None, alias="googleMapsUri")
    national_phone_number: Optional[str] = Field(
        default=None, alias="nationalPhoneNumber"
    )
    website_uri: Optional[str] = Field(default=None, alias="websiteUri")
    current_opening_hours: Optional[OpeningHours] = Field(
        default=None, alias="currentOpeningHours"
    )
    regular_opening_hours: Optional[OpeningHours] = Field(
        default=None, alias="regularOpeningHours"
    )
    rating: Optional[float] = None
    user_rating_count: Optional[int] = Field(default=None, alias="userRatingCount")
    price_range: Optional[Any] = Field(default=None, alias="priceRange")
    price_level: Optional[str] = Field(default=None, alias="priceLevel")


class PlaceSearchRequest(ApiModel):
    query: str = Field(
        min_length=1,
        max_length=500,
        description="Postcode, full address, landmark, or natural-language place query.",
        examples=["restaurants near 018956 Singapore"],
    )
    max_results: int = Field(default=5, ge=1, le=20)
    language_code: str = Field(
        default=DEFAULT_LANGUAGE_CODE,
        alias="languageCode",
        description="BCP-47 response language. Defaults to English.",
    )
    region_code: str = Field(
        default=DEFAULT_REGION_CODE,
        alias="regionCode",
        min_length=2,
        max_length=2,
        description="Two-letter result region. Defaults to Singapore (SG).",
    )


class PlaceSearchResponse(ApiModel):
    query: str
    count: int
    places: List[Place]


class RankPreference(str, Enum):
    popularity = "POPULARITY"
    distance = "DISTANCE"


class NearbySearchRequest(ApiModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_meters: float = Field(default=1000, gt=0, le=50_000)
    included_types: List[str] = Field(
        default_factory=list,
        max_length=50,
        description="Google place types such as restaurant or cafe.",
        examples=[["restaurant", "cafe"]],
    )
    max_results: int = Field(default=10, ge=1, le=20)
    rank_preference: RankPreference = RankPreference.popularity
    language_code: str = Field(
        default=DEFAULT_LANGUAGE_CODE,
        min_length=2,
        description="BCP-47 response language. Defaults to English.",
    )
    region_code: str = Field(
        default=DEFAULT_REGION_CODE,
        min_length=2,
        max_length=2,
        description="Two-letter result region. Defaults to Singapore (SG).",
    )

    @field_validator("included_types")
    @classmethod
    def validate_included_types(cls, values: List[str]) -> List[str]:
        normalized = [value.strip().lower() for value in values]
        unknown = sorted(set(normalized) - GOOGLE_PLACE_FILTER_TYPES)
        if unknown:
            raise ValueError(
                "Unsupported Google place type(s): " + ", ".join(unknown)
            )
        return normalized


class NearbySearchResponse(ApiModel):
    center: Coordinates
    radius_meters: float
    count: int
    places: List[Place]
