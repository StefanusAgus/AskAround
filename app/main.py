import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import ConfigurationError
from app.constants import GOOGLE_API_TIMEOUT_SECONDS
from app.routers.agent import router as agent_router
from app.routers.places import router as places_router
from app.services.google_places import GooglePlacesError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpx2").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(timeout=GOOGLE_API_TIMEOUT_SECONDS) as client:
        app.state.http_client = client
        yield


app = FastAPI(
    title="Nearby Locator API",
    description="Search Google Maps places by text or nearby location.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(places_router)
app.include_router(agent_router)


@app.exception_handler(ConfigurationError)
async def configuration_error_handler(
    request: Request, exc: ConfigurationError
) -> JSONResponse:
    logger.error(
        "%s %s failed: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={"error": "configuration_error", "detail": str(exc)},
    )


@app.exception_handler(GooglePlacesError)
async def google_places_error_handler(
    request: Request, exc: GooglePlacesError
) -> JSONResponse:
    logger.error(
        "%s %s failed: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "google_places_error", "detail": str(exc)},
    )


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
