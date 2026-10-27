import os

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field


class ConfigurationError(RuntimeError):
    """Raised when a required application setting is missing."""


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    google_maps_api_key: str = Field(min_length=1)

    @classmethod
    def from_environment(cls) -> "Settings":
        load_dotenv()
        api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not api_key:
            raise ConfigurationError(
                "GOOGLE_MAPS_API_KEY is not set. Copy .env.example to .env or "
                "set the variable in your shell before starting the API."
            )
        return cls(google_maps_api_key=api_key)
