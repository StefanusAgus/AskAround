from enum import Enum
from typing import List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.constants import (
    DEFAULT_LANGUAGE_CODE,
    DEFAULT_REGION_CODE,
    GOOGLE_PLACE_FILTER_TYPES,
    ISO_3166_ALPHA_2_REGION_CODES,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class DisplayName(ApiModel):
    text: str
    language_code: Optional[str] = Field(default=None, alias="languageCode")


class Coordinates(ApiModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class OpeningHours(ApiModel):
    open_now: Optional[bool] = Field(default=None, alias="openNow")
    weekday_descriptions: List[str] = Field(
        default_factory=list, alias="weekdayDescriptions"
    )


class Money(ApiModel):
    currency_code: str = Field(alias="currencyCode", min_length=3, max_length=3)
    units: int = 0
    nanos: int = Field(default=0, ge=-999_999_999, le=999_999_999)

    @field_validator("currency_code")
    @classmethod
    def normalize_currency_code(cls, value: str) -> str:
        return value.upper()


class PriceRange(ApiModel):
    start_price: Optional[Money] = Field(default=None, alias="startPrice")
    end_price: Optional[Money] = Field(default=None, alias="endPrice")

    @model_validator(mode="after")
    def require_price_bound(self) -> "PriceRange":
        if self.start_price is None and self.end_price is None:
            raise ValueError("priceRange requires startPrice or endPrice")
        return self


class PriceLevel(str, Enum):
    unspecified = "PRICE_LEVEL_UNSPECIFIED"
    free = "PRICE_LEVEL_FREE"
    inexpensive = "PRICE_LEVEL_INEXPENSIVE"
    moderate = "PRICE_LEVEL_MODERATE"
    expensive = "PRICE_LEVEL_EXPENSIVE"
    very_expensive = "PRICE_LEVEL_VERY_EXPENSIVE"


class Place(ApiModel):
    id: str = Field(min_length=1)
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
    rating: Optional[float] = Field(default=None, ge=0, le=5)
    user_rating_count: Optional[int] = Field(
        default=None,
        alias="userRatingCount",
        ge=0,
    )
    price_range: Optional[PriceRange] = Field(default=None, alias="priceRange")
    price_level: Optional[PriceLevel] = Field(default=None, alias="priceLevel")


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

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()

    @field_validator("region_code")
    @classmethod
    def validate_region_code(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in ISO_3166_ALPHA_2_REGION_CODES:
            raise ValueError("regionCode must be an ISO 3166-1 alpha-2 code")
        return normalized


class PlaceSearchResponse(ApiModel):
    query: str
    count: int = Field(ge=0)
    places: List[Place]

    @model_validator(mode="after")
    def validate_count(self) -> "PlaceSearchResponse":
        if self.count != len(self.places):
            raise ValueError("count must equal the number of places")
        return self


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

    @field_validator("region_code")
    @classmethod
    def validate_region_code(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in ISO_3166_ALPHA_2_REGION_CODES:
            raise ValueError("region_code must be an ISO 3166-1 alpha-2 code")
        return normalized


class NearbySearchResponse(ApiModel):
    center: Coordinates
    radius_meters: float
    count: int = Field(ge=0)
    places: List[Place]

    @model_validator(mode="after")
    def validate_count(self) -> "NearbySearchResponse":
        if self.count != len(self.places):
            raise ValueError("count must equal the number of places")
        return self
