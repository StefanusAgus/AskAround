import json
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.agent.models import AgentChatRequest, AgentStreamEvent
from app.agent.service import AgentService
from app.config import OpenRouterSettings

router = APIRouter(prefix="/agent", tags=["agent"])


def get_agent_service() -> AgentService:
    return AgentService(OpenRouterSettings.from_environment())


def format_sse(stream_event: AgentStreamEvent) -> str:
    data = json.dumps(stream_event.data, ensure_ascii=False)
    return f"event: {stream_event.event}\ndata: {data}\n\n"


@router.post(
    "/chat",
    response_class=StreamingResponse,
    summary="Stream a response from the AskAround agent",
)
async def chat_with_agent(
    request: AgentChatRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        async for stream_event in service.stream(request.message, request.session_id):
            yield format_sse(stream_event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
