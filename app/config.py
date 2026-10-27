import os

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from app.constants import DEFAULT_OPENROUTER_MODEL


class ConfigurationError(RuntimeError):
    """Raised when a required application setting is missing."""


class GoogleMapsSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    google_maps_api_key: str = Field(min_length=1)

    @classmethod
    def from_environment(cls) -> "GoogleMapsSettings":
        load_dotenv()
        api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not api_key:
            raise ConfigurationError(
                "GOOGLE_MAPS_API_KEY is not set. Copy .env.example to .env or "
                "set the variable in your shell before starting the API."
            )
        return cls(google_maps_api_key=api_key)


class OpenRouterSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_key: str = Field(min_length=1)
    model: str = Field(min_length=1)

    @classmethod
    def from_environment(cls) -> "OpenRouterSettings":
        load_dotenv()
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ConfigurationError(
                "OPENROUTER_API_KEY is not set. Add it to .env before using "
                "the agent endpoint."
            )
        return cls(
            api_key=api_key,
            model=os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
        )
